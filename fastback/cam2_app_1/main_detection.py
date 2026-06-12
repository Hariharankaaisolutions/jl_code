# main_detection.py — YOLOv5 Detection Core (Supervision + ByteTrack)
# ==================================================================
# Changes from dual-model version:
#   - Single model inference (MODEL_PATH replaces BOX/BALE split)
#   - DETECTION_MODE=grayscale → convert frame to gray before inference
#   - Color frame is always kept separately for display & saves
#   - RAW_VIDEO_GRAYSCALE / DETECTED_VIDEO_GRAYSCALE / DETECTED_FRAME_GRAYSCALE
#     switches control what gets saved (only active in grayscale mode)
#   - imshow always shows the color annotated frame
#   - All other logic (ghost, OR-gate, ByteTrack) is UNCHANGED
# ==================================================================

# 🔴 smart_logger MUST be first
from smart_logger import get_logger
logger = get_logger(__name__)

import asyncio
import cv2
import torch
import time
from datetime import datetime

import supervision as sv

from session import session_manager
from mqtt_push import mqtt_push_error
from message_loader import Messages

from main_config import (
    YOLOV5_PATH,
    MODEL_PATH,
    FRAME_WIDTH,
    FRAME_HEIGHT,
    CROSS_LINE_X,
    ENTRY_LINE_X,
    CONF_THRES,
    GHOST_MATCH_DIST_PX,
    GHOST_MAX_AGE_FRAMES,
    DETECTION_MODE,
    DETECTED_VIDEO_GRAYSCALE,
    DETECTED_FRAME_GRAYSCALE,
)

from main_health_check import (
    check_memory,
    check_disk_space,
    check_fps,
)

from main_opencv_gui import gui_available


# -------------------------------------------------
# Derived mode flags (computed once at import time)
# -------------------------------------------------
_GRAYSCALE_MODE = DETECTION_MODE == "grayscale"

# In grayscale mode: should the annotated video written to disk be gray?
_SAVE_DETECTED_VIDEO_GRAY = _GRAYSCALE_MODE and DETECTED_VIDEO_GRAYSCALE

# In grayscale mode: should the trip/frame captures be gray?
_SAVE_DETECTED_FRAME_GRAY = _GRAYSCALE_MODE and DETECTED_FRAME_GRAYSCALE


# -------------------------------------------------
# Class Weights
# -------------------------------------------------
CLASS_WEIGHTS = {
    "box":     1,
    "bale":    1,
    "trolley": 0,
}


# -------------------------------------------------
# Double-line geometry helpers
# -------------------------------------------------
def _box_centroid(xyxy):
    """Return (cx, cy) float centroid of a bounding box."""
    return ((xyxy[0] + xyxy[2]) / 2.0, (xyxy[1] + xyxy[3]) / 2.0)


def _point_dist(a, b):
    """Euclidean distance between two (x,y) points."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


# -------------------------------------------------
# Transaction ID helper
# -------------------------------------------------
def get_tx_for_session(session_id: str):
    try:
        sess = session_manager.sessions.get(session_id)
        return sess.get("transaction_id") if sess else None
    except Exception:
        logger.exception(
            Messages.get("SESSION.TXID.001.ERROR", session_id=session_id)
        )
        return None


# -------------------------------------------------
# YOLOv5 Model Singleton (SINGLE MODEL)
# -------------------------------------------------
_model  = None
_device = None


def get_model():
    global _model, _device

    if _model is None:

        _device = "cuda:0" if torch.cuda.is_available() else "cpu"

        logger.info(
            Messages.get(
                "YOLO.LOAD.001.INFO",
                yolo_path=YOLOV5_PATH,
                model_path=MODEL_PATH,
            )
        )

        _model = torch.hub.load(
            YOLOV5_PATH,
            "custom",
            path=MODEL_PATH,
            source="local",
        )

        _model.conf = CONF_THRES
        _model.to(_device)

        # ── Prominent device banner ───────────────────────────────────────────
        _cuda_available = torch.cuda.is_available()
        _gpu_name       = torch.cuda.get_device_name(0) if _cuda_available else ""
        _device_label   = (
            f"GPU  ({_gpu_name})"
            if _cuda_available
            else "CPU  (CUDA not available)"
        )
        _model_display  = MODEL_PATH if len(MODEL_PATH) <= 40 else f"...{MODEL_PATH[-40:]}"
        _banner = (
            "\n"
            "╔══════════════════════════════════════════════════════╗\n"
            "║              YOLO MODEL LOAD SUMMARY                ║\n"
            "╠══════════════════════════════════════════════════════╣\n"
            f"║  Device    : {_device_label:<40}║\n"
            f"║  Model     : {_model_display:<40}║\n"
            f"║  Conf      : {str(CONF_THRES):<40}║\n"
            f"║  Inf mode  : {DETECTION_MODE:<40}║\n"
            "╚══════════════════════════════════════════════════════╝"
        )
        print(_banner, flush=True)
        logger.info(_banner)

        logger.info(
            Messages.get("YOLO.LOAD.002.INFO", device=_device)
        )

    return _model


# -------------------------------------------------
# Frame preparation helpers
# -------------------------------------------------
def _prepare_inference_frame(color_bgr):
    """
    Return the frame that will be fed to the YOLO model.

    - rgb mode  : convert BGR → RGB  (3-channel, same as before)
    - grayscale : convert BGR → gray → stack to 3-channel RGB-like
                  (model expects 3 channels; stacking gray gives neutral input)
    """
    if _GRAYSCALE_MODE:
        gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
        # Stack to 3-channel so model input shape is unchanged
        gray3 = cv2.merge([gray, gray, gray])
        return gray3   # already "RGB-equivalent" (all channels identical)
    else:
        return cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)


def _make_save_frame(color_annotated_bgr):
    """
    Return the frame that will be written to the detected video / trip frames.

    - rgb mode         : always color
    - grayscale mode   : gray or color depending on per-switch flags
    """
    if not _GRAYSCALE_MODE:
        return color_annotated_bgr

    # grayscale mode — convert only if the switch demands it
    # (caller decides which flag to use: video vs frame)
    gray = cv2.cvtColor(color_annotated_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)   # keep 3-ch for VideoWriter


# -------------------------------------------------
# Detection Core
# -------------------------------------------------
async def detect_objects(video_source: str, session_id: str):

    logger.info(
        Messages.get(
            "DETECTION.START.001.INFO",
            session_id=session_id,
            video_source=video_source,
        )
    )

    start_ts        = datetime.now()
    loop_start_time = time.time()

    model = get_model()

    transaction_id = get_tx_for_session(session_id)

    tracker = sv.ByteTrack(
        track_activation_threshold=0.5,
        lost_track_buffer=60,
        minimum_matching_threshold=0.7,
    )

    box_annotator   = sv.BoxAnnotator(thickness=3)
    label_annotator = sv.LabelAnnotator(text_scale=0.6, text_thickness=2)

    # ── Per-track state ───────────────────────────────────────────────────────
    prev_x      = {}   # tid → last known cx (int)
    prev_xyxy   = {}   # tid → last known xyxy (for ghost position)
    track_class = {}   # tid → class name string

    line1_triggered = set()   # tids that crossed ENTRY_LINE_X (LINE1)
    line2_triggered = set()   # tids that crossed CROSS_LINE_X  (LINE2 / final)
    counted_ids     = set()   # tids fully committed (never counted again)

    # ── Ghost table ───────────────────────────────────────────────────────────
    ghost_line1    = {}   # ghost_key → { centroid, class, frame, origin_id }
    tid_lost_since = {}   # tid → frame_index of first disappearance

    active_tids_prev = set()
    # ─────────────────────────────────────────────────────────────────────────

    cap = None

    try:

        cap = cv2.VideoCapture(video_source, cv2.CAP_FFMPEG)

        if not cap.isOpened():

            mqtt_push_error(
                session_id=session_id,
                transaction_id=transaction_id,
                error_code="CAMERA_DISCONNECTED",
                message="Camera source could not be opened",
                severity="critical",
            )

            session_manager.stop_session(session_id)
            return

        counts = session_manager.get_counts(session_id)

        frame_index     = 0
        last_disk_check = time.time()
        fps_warned      = False

        if gui_available():
            try:
                win = f"Detection-{session_id}"
                cv2.namedWindow(win, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(win, FRAME_WIDTH, FRAME_HEIGHT)
            except Exception:
                logger.exception("OpenCV GUI init failed")

        # =====================================================================
        # MAIN LOOP
        # =====================================================================
        while session_manager.is_active(session_id):

            frame_index += 1
            ret, frame = cap.read()

            if not ret:

                mqtt_push_error(
                    session_id=session_id,
                    transaction_id=transaction_id,
                    error_code="NO_FRAMES",
                    message="No frames received from camera source",
                    severity="high",
                )

                break

            # ── Health checks ─────────────────────────────────────────────────
            if frame_index % 60 == 0:

                check_memory(session_id, transaction_id)

                if not fps_warned:
                    fps_warned, _ = check_fps(
                        session_id,
                        transaction_id,
                        frame_index,
                        loop_start_time,
                    )

            if time.time() - last_disk_check > 30:
                last_disk_check = time.time()
                check_disk_space(session_id, transaction_id)

            try:
                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
            except Exception:
                pass

            # color_frame is always the original BGR color frame — used for
            # display (imshow) and optionally for saves.
            color_frame = frame.copy()

            if not session_manager.sessions[session_id]["first_frame_saved"]:
                # First frame is always saved in color regardless of mode
                session_manager.video_saver.save_first_frame(session_id, color_frame)
                session_manager.sessions[session_id]["first_frame_saved"] = True

            # -----------------------------------------------------------------
            # YOLO SINGLE-MODEL INFERENCE
            # -----------------------------------------------------------------
            detections_list = []
            confidences     = []
            class_ids       = []

            try:

                inference_frame = _prepare_inference_frame(color_frame)

                results = model(inference_frame)

                if len(results.xyxy[0]) > 0:
                    for det in results.xyxy[0]:
                        x1, y1, x2, y2, conf, cls = det.cpu().numpy()
                        detections_list.append([x1, y1, x2, y2])
                        confidences.append(conf)
                        class_ids.append(int(cls))

                if len(detections_list) > 0:
                    detections = sv.Detections(
                        xyxy=torch.tensor(detections_list).numpy(),
                        confidence=torch.tensor(confidences).numpy(),
                        class_id=torch.tensor(class_ids).numpy(),
                    )
                else:
                    detections = sv.Detections.empty()

            except Exception as e:

                mqtt_push_error(
                    session_id=session_id,
                    transaction_id=transaction_id,
                    error_code="YOLO_INFERENCE_ERROR",
                    message=str(e),
                    severity="high",
                )

                detections = sv.Detections.empty()

            detections = tracker.update_with_detections(detections)

            active_tids_now = set()

            # =================================================================
            # STEP 1 — Expire old ghosts
            # =================================================================
            expired_keys = [
                k for k, g in ghost_line1.items()
                if frame_index - g["frame"] > GHOST_MAX_AGE_FRAMES
            ]
            for k in expired_keys:
                g      = ghost_line1.pop(k)
                cname  = g["class"]
                weight = CLASS_WEIGHTS.get(cname, 1)
                if weight > 0:
                    for _ in range(weight):
                        counts = session_manager.update_counts(
                            session_id, cname, frame=None
                        )
                    logger.info(
                        Messages.get(
                            "DETECTION.CROSSING.001.INFO",
                            session_id=session_id,
                            object_id=g["origin_id"],
                            label=cname,
                            counts=counts,
                        )
                    )

            # =================================================================
            # STEP 2 — Build annotated frame on COLOR frame
            # =================================================================
            labels = [
                f"{track_class.get(tid, 'UNK')} {conf:.2f} ID:{tid}"
                for tid, conf in zip(
                    detections.tracker_id,
                    detections.confidence,
                )
            ]

            annotated_color = box_annotator.annotate(color_frame.copy(), detections)
            annotated_color = label_annotator.annotate(annotated_color, detections, labels)

            cv2.line(
                annotated_color,
                (ENTRY_LINE_X, 0), (ENTRY_LINE_X, FRAME_HEIGHT),
                (0, 255, 255), 2,
            )
            cv2.putText(
                annotated_color, "LINE1",
                (ENTRY_LINE_X + 5, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2,
            )

            cv2.line(
                annotated_color,
                (CROSS_LINE_X, 0), (CROSS_LINE_X, FRAME_HEIGHT),
                (255, 255, 255), 3,
            )
            cv2.putText(
                annotated_color, "LINE2",
                (CROSS_LINE_X + 5, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
            )

            cv2.putText(
                annotated_color,
                f"Box:{counts['box']} | Bale:{counts['bale']} | Trolley:{counts['trolley']}",
                (10, FRAME_HEIGHT - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
            )

            if _SAVE_DETECTED_VIDEO_GRAY:
                video_write_frame = _make_save_frame(annotated_color)
            else:
                video_write_frame = annotated_color

            # =================================================================
            # STEP 3 — Per-detection double-line OR-gate logic (UNCHANGED)
            # =================================================================
            for xyxy, tid, cid in zip(
                detections.xyxy,
                detections.tracker_id,
                detections.class_id,
            ):
                if tid is None:
                    continue

                active_tids_now.add(tid)
                tid_lost_since.pop(tid, None)

                cpos = _box_centroid(xyxy)
                cx   = int(cpos[0])

                if tid not in track_class:
                    cname = model.names.get(int(cid), str(cid))
                    track_class[tid] = cname

                cname  = track_class[tid]
                weight = CLASS_WEIGHTS.get(cname, 1)

                if tid not in prev_x and CROSS_LINE_X <= cx <= ENTRY_LINE_X:
                    best_key  = None
                    best_dist = float("inf")
                    for gk, g in ghost_line1.items():
                        if g["class"] != cname:
                            continue
                        d = _point_dist(cpos, g["centroid"])
                        if d < best_dist and d < GHOST_MATCH_DIST_PX:
                            best_dist = d
                            best_key  = gk

                    if best_key is not None:
                        g = ghost_line1.pop(best_key)
                        line1_triggered.add(tid)
                        logger.debug(
                            f"[GHOST-MATCH] {cname} new-ID:{tid} <- "
                            f"origin-ID:{g['origin_id']} (dist={best_dist:.1f}px)"
                        )

                if tid in prev_x:
                    old_cx = prev_x[tid]

                    if old_cx > ENTRY_LINE_X >= cx and tid not in line1_triggered:
                        line1_triggered.add(tid)
                        logger.debug(f"[LINE1] {cname} ID:{tid} crossed entry line")

                    if old_cx > CROSS_LINE_X >= cx and tid not in line2_triggered:
                        line2_triggered.add(tid)
                        logger.debug(f"[LINE2] {cname} ID:{tid} crossed final line")

                should_count = False
                if tid not in counted_ids:
                    if tid in line2_triggered:
                        should_count = True
                    elif tid in line1_triggered and cx < CROSS_LINE_X - 30:
                        should_count = True

                if should_count:
                    counted_ids.add(tid)
                    stale = [
                        gk for gk, g in ghost_line1.items()
                        if g["origin_id"] == tid
                    ]
                    for gk in stale:
                        ghost_line1.pop(gk)

                    if weight > 0:
                        if _SAVE_DETECTED_FRAME_GRAY:
                            save_frame = _make_save_frame(annotated_color)
                        else:
                            save_frame = annotated_color

                        for _ in range(weight):
                            counts = session_manager.update_counts(
                                session_id,
                                cname,
                                frame=save_frame,
                            )
                        logger.info(
                            Messages.get(
                                "DETECTION.CROSSING.001.INFO",
                                session_id=session_id,
                                object_id=tid,
                                label=cname,
                                counts=counts,
                            )
                        )

                prev_x[tid]    = cx
                prev_xyxy[tid] = xyxy

            # =================================================================
            # STEP 4 — Track dropped IDs and create ghosts (UNCHANGED)
            # =================================================================
            dropped = active_tids_prev - active_tids_now

            for tid in dropped:
                if tid not in tid_lost_since:
                    tid_lost_since[tid] = frame_index

            for tid in list(tid_lost_since.keys()):

                if tid in active_tids_now:
                    tid_lost_since.pop(tid, None)
                    continue

                frames_missing = frame_index - tid_lost_since[tid]

                if frames_missing < 3:
                    continue

                already_ghosted = any(
                    g["origin_id"] == tid for g in ghost_line1.values()
                )

                if (
                    tid in line1_triggered
                    and tid not in counted_ids
                    and tid not in line2_triggered
                    and tid in prev_xyxy
                    and not already_ghosted
                ):
                    last_pos  = _box_centroid(prev_xyxy[tid])
                    ghost_key = f"{tid}_{frame_index}"
                    ghost_line1[ghost_key] = {
                        "centroid":  last_pos,
                        "class":     track_class.get(tid, "unknown"),
                        "frame":     frame_index,
                        "origin_id": tid,
                    }
                    logger.debug(
                        f"[GHOST-CREATE] ID:{tid} missing {frames_missing}f "
                        f"-> ghost at ({last_pos[0]:.0f},{last_pos[1]:.0f})"
                    )

                tid_lost_since.pop(tid, None)

            active_tids_prev = active_tids_now

            # =================================================================
            # STEP 5 — Write / display frame
            # =================================================================
            session_manager.video_saver.write_frame(session_id, video_write_frame)
            session_manager.set_counts(session_id, counts)

            if gui_available():
                cv2.imshow(win, annotated_color)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    session_manager.stop_session(session_id)
                    break

            await asyncio.sleep(0)

        # ── End of loop ───────────────────────────────────────────────────────
        cap.release()

        if gui_available():
            cv2.destroyAllWindows()

        logger.info(
            Messages.get(
                "DETECTION.STOP.001.INFO",
                session_id=session_id,
                duration=(datetime.now() - start_ts),
            )
        )

    except Exception:

        logger.exception(
            Messages.get(
                "DETECTION.EXCEPTION.001.ERROR",
                session_id=session_id,
            )
        )

        mqtt_push_error(
            session_id=session_id,
            transaction_id=transaction_id,
            error_code="DETECTION_EXCEPTION",
            message="Unexpected detection error",
            severity="high",
        )

        session_manager.stop_session(session_id)