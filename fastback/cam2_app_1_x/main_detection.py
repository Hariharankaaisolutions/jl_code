# main_detection.py — YOLOX Detection Core (Supervision + ByteTrack)
# ==================================================================
# Model             : YOLOX (.pth only)
# Inference         : ValTransform + postprocess (YOLOX native)
# Counting          : Single line (CROSS_LINE_X)
# Direction         : Configurable via CROSS_DIRECTION in app.properties
# Class assignment  : Confidence voting — accumulated per track
# Ghost Tracking    : Disabled
# GUI guard         : gui_available() + ENABLE_GUI flag
# Overlay           : 1 white count line + single count bar bottom-left
# ByteTrack         : activation=0.5, buffer=60, matching=0.7
# Grayscale         : Configurable via DETECTION_MODE in app.properties
# Freeze detection  : END_SESSION_ON_VIDEO_FREEZE / MAX_FREEZE_FRAMES
# Window            : Lazy creation — opens on first frame (safe)
# Preload           : Model loaded lazily on first call (YOLOX style)
#
# TROLLEY COUNTING:
#   Trolley is NOT counted here. session.py.update_counts() increments
#   trolley once per 3-second window whenever any box/bale crossing fires.
#   main_detection.py only detects box and bale line crossings and calls
#   session_manager.update_counts(label). Trolley logic lives entirely
#   in session.py.
#
# CLASS_NAMES must match your annotations.coco.json label order exactly.
#   box-Sedr (index 0) is a spurious label — silently skipped by CLASS_WEIGHTS gate.
#   All other labels must be present in BOX_CLASSES or BALE_CLASSES in app.properties.
# ================================================================

# 🔴 smart_logger MUST be first
from smart_logger import get_logger
logger = get_logger(__name__)

import asyncio
import cv2
import torch
import os
import time
from datetime import datetime
from collections import defaultdict

import numpy as np
import supervision as sv

from yolox.exp import get_exp
from yolox.utils import postprocess, fuse_model
from yolox.data.data_augment import ValTransform

from session import session_manager
from mqtt_push import mqtt_push_error
from message_loader import Messages

from main_config import (
    EXP_FILE,
    MODEL_PATH,
    FRAME_WIDTH,
    FRAME_HEIGHT,
    CROSS_LINE_X,
    CONF_THRES,
    IOU_THRES,
    CROSS_DIRECTION,
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

from config_loader import (
    ASYNC_SLEEP_TIME,
    ENABLE_GUI,
    END_SESSION_ON_VIDEO_FREEZE,
    MAX_FREEZE_FRAMES,
    BOX_CLASSES,
    BALE_CLASSES,
    BAG_CLASSES,
    RL_SAVE_DIR,
    RL_CONF_THRESHOLD,
    RL_LINE_PROXIMITY_PX,
)

# -------------------------------------------------
# Derived mode flags (computed once at import time)
# -------------------------------------------------
_GRAYSCALE_MODE           = DETECTION_MODE == "grayscale"
_SAVE_DETECTED_VIDEO_GRAY = _GRAYSCALE_MODE and DETECTED_VIDEO_GRAYSCALE
_SAVE_DETECTED_FRAME_GRAY = _GRAYSCALE_MODE and DETECTED_FRAME_GRAYSCALE


# -------------------------------------------------
# Class Weights — built dynamically from app.properties.
#
# All labels from BOX_CLASSES and BALE_CLASSES are included
# with weight=1 as a gate (the actual increment amount is
# handled inside session.py via BOX_CLASSES / BALE_CLASSES).
#
# Trolley is NOT included here. session.py handles trolley
# via a 3-second window gate on every box/bale crossing.
#
# Example (from app.properties):
#   BOX_CLASSES  = box:1
#   BALE_CLASSES = bale:1,fbale:1,sbale:2,tbale_a:2,tbale_b:2
#
# Result:
#   CLASS_WEIGHTS = {
#       'box': 1,
#       'bale': 1, 'fbale': 1, 'sbale': 1, 'tbale_a': 1, 'tbale_b': 1
#   }
# -------------------------------------------------
CLASS_WEIGHTS = {
    **{label: 1 for label in BOX_CLASSES},
    **{label: 1 for label in BALE_CLASSES},
    **{label: 1 for label in BAG_CLASSES},
}

logger.info(f"CLASS_WEIGHTS loaded: {CLASS_WEIGHTS}")


# -------------------------------------------------
# Class Names — must match your annotations.coco.json label order exactly.
#
# Index 0 (box-Sedr) is a spurious label produced by the annotation tool.
# It is NOT in CLASS_WEIGHTS so it is silently skipped during counting.
#
# If your model has different classes or a different order, update this
# dict to match your annotations.coco.json exactly.
# -------------------------------------------------
CLASS_NAMES = {
    0: "bag-XY17",  # spurious — ignored by CLASS_WEIGHTS gate
    1: "2bag",
    2: "3bag",
    3: "4bag",
    4: "bag",
}

logger.info(f"CLASS_NAMES loaded: {CLASS_NAMES}")


# -------------------------------------------------
# Geometry helper
# -------------------------------------------------
def _box_centroid(xyxy):
    """Return (cx, cy) float centroid of a bounding box."""
    return ((xyxy[0] + xyxy[2]) / 2.0, (xyxy[1] + xyxy[3]) / 2.0)


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
# YOLOX Model Singleton — lazy load on first call
# -------------------------------------------------
_model      = None
_exp        = None
_device     = None
_name_to_id = {}


def get_model():
    """
    Load YOLOX .pth model on first call and cache globally.
    Subsequent calls return the cached (model, exp) tuple instantly.
    """
    global _model, _exp, _device, _name_to_id

    if _model is not None:
        return _model, _exp

    _device = "cuda:0" if torch.cuda.is_available() else "cpu"

    logger.info(
        Messages.get(
            "YOLO.LOAD.001.INFO",
            exp_file=EXP_FILE,
            model_path=MODEL_PATH,
        )
    )

    try:
        _exp   = get_exp(EXP_FILE)
        _model = _exp.get_model()
        _model.to(_device)
        _model.eval()

        ckpt = torch.load(MODEL_PATH, map_location=_device, weights_only=False)
        _model.load_state_dict(ckpt["model"])
        _model = fuse_model(_model)

        # Override thresholds from app.properties
        _exp.test_conf = CONF_THRES
        _exp.nmsthre   = IOU_THRES

        _name_to_id = {v: k for k, v in CLASS_NAMES.items()}

    except Exception:
        logger.exception(Messages.get("YOLO.LOAD.003.ERROR"))
        raise

    logger.info(Messages.get("YOLO.LOAD.002.INFO", device=_device))
    return _model, _exp


# -------------------------------------------------
# YOLOX Inference helper
# -------------------------------------------------
def run_yolox_inference(model, exp, frame_rgb, device):
    """
    Run YOLOX inference on a single RGB frame.

    Returns numpy array of shape (N, 7):
        [:, 0:4] — xyxy bounding boxes (already scaled to frame size)
        [:, 4]   — objectness confidence
        [:, 5]   — class confidence
        [:, 6]   — class id (int)

    Returns empty (0, 7) array when no detections.
    """
    preproc       = ValTransform(legacy=False)
    img, _        = preproc(frame_rgb, None, exp.test_size)
    height, width = frame_rgb.shape[:2]
    ratio         = min(exp.test_size[0] / height, exp.test_size[1] / width)
    img           = torch.from_numpy(img).unsqueeze(0).to(device).float()

    with torch.no_grad():
        outputs = model(img)
        outputs = postprocess(
            outputs, exp.num_classes, exp.test_conf, exp.nmsthre
        )

    if outputs[0] is None:
        return np.empty((0, 7))

    detections          = outputs[0].cpu().numpy()
    detections[:, 0:4] /= ratio
    return detections


# -------------------------------------------------
# Frame preparation helpers
# -------------------------------------------------
def _prepare_inference_frame(color_bgr: np.ndarray) -> np.ndarray:
    """
    Prepare frame for model input.
    grayscale mode → BGR→gray→3ch (neutral input, keeps model shape)
    rgb mode       → BGR→RGB
    """
    if _GRAYSCALE_MODE:
        gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
        return cv2.merge([gray, gray, gray])
    return cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)


def _make_save_frame(color_annotated_bgr: np.ndarray) -> np.ndarray:
    """Convert annotated color frame to 3-ch gray for saving."""
    gray = cv2.cvtColor(color_annotated_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

# -------------------------------------------------
# Reinforcement Learning Frame Saver
# -------------------------------------------------
def _save_rl_frame(
    color_frame,
    session_id: str,
    transaction_id: str,
    label: str,
    confidence: float,
):
    """
    Save a raw color frame (no bounding boxes) with only a text overlay
    showing label + confidence, for reinforcement learning review.

    Folder structure:
        RL_SAVE_DIR / YYYY-MM-DD / transaction_id / transaction_id_HHMMSS_ffffff.jpg
    """
    try:
        date_str = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%H%M%S_%f")
        filename  = f"{transaction_id}_{timestamp}.jpg"

        save_dir = os.path.join(RL_SAVE_DIR, date_str, transaction_id)
        os.makedirs(save_dir, exist_ok=True)

        filepath = os.path.join(save_dir, filename)

        # Copy raw frame — no bounding boxes
        frame_copy = color_frame.copy()

        # Write label + confidence as text only
        text = f"{label} {confidence:.3f}"
        cv2.putText(
            frame_copy,
            text,
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 0, 255),   # red text so it stands out
            2,
            cv2.LINE_AA,
        )

        cv2.imwrite(filepath, frame_copy)
        logger.debug(
            f"RL frame saved → session={session_id} label={label} "
            f"conf={confidence:.3f} path={filepath}"
        )

    except Exception:
        logger.exception(
            f"Failed to save RL frame for session={session_id} "
            f"transaction={transaction_id}"
        )

# -------------------------------------------------
# Detection core
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

    # Model loads here on first session — lazy, YOLOX style
    model, exp     = get_model()
    transaction_id = get_tx_for_session(session_id)

    tracker = sv.ByteTrack(
        track_activation_threshold=0.5,
        lost_track_buffer=60,
        minimum_matching_threshold=0.7,
    )

    box_annotator   = sv.BoxAnnotator(thickness=3)
    label_annotator = sv.LabelAnnotator(text_scale=0.6, text_thickness=2)

    # tid → last known cx
    prev_x = {}

    # Confidence voting: tid → {class_name → accumulated_confidence}
    # More robust than single highest-conf — prevents flicker from locking
    # the wrong class early in a track.
    track_class_votes = defaultdict(lambda: defaultdict(float))

    counted_ids = set()

    def get_best_class(tid):
        """Return the class name with the highest accumulated vote for tid."""
        votes = track_class_votes.get(tid)
        if not votes:
            return None
        return max(votes, key=votes.get)

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

        counts          = session_manager.get_counts(session_id)
        frame_index     = 0
        freeze_count    = 0
        last_disk_check = time.time()
        fps_warned      = False

        # Lazy window — created on first frame, never before
        win = None

        # =====================================================================
        # MAIN LOOP
        # =====================================================================
        while session_manager.is_active(session_id):

            frame_index += 1
            ret, frame = cap.read()

            if not ret:
                if END_SESSION_ON_VIDEO_FREEZE:
                    freeze_count += 1
                    if freeze_count >= MAX_FREEZE_FRAMES:
                        logger.warning(
                            Messages.get(
                                "CAMERA.FRAME.001.WARN",
                                session_id=session_id,
                                frame_index=frame_index,
                            )
                        )
                        mqtt_push_error(
                            session_id=session_id,
                            transaction_id=transaction_id,
                            error_code="NO_FRAMES",
                            message="No frames received from camera source",
                            severity="high",
                        )
                        break
                    await asyncio.sleep(ASYNC_SLEEP_TIME or 0.05)
                    continue
                else:
                    mqtt_push_error(
                        session_id=session_id,
                        transaction_id=transaction_id,
                        error_code="NO_FRAMES",
                        message="No frames received from camera source",
                        severity="high",
                    )
                    break
            else:
                freeze_count = 0

            # ── Health checks every 60 frames ─────────────────────────────
            if frame_index % 60 == 0:
                check_memory(session_id, transaction_id)
                if not fps_warned:
                    fps_warned, _ = check_fps(
                        session_id, transaction_id,
                        frame_index, loop_start_time,
                    )

            if time.time() - last_disk_check > 30:
                last_disk_check = time.time()
                check_disk_space(session_id, transaction_id)

            try:
                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
            except Exception:
                pass

            color_frame = frame.copy()

            # Save first frame (always color)
            if not session_manager.sessions[session_id]["first_frame_saved"]:
                session_manager.video_saver.save_first_frame(
                    session_id, color_frame
                )
                session_manager.sessions[session_id]["first_frame_saved"] = True

            # -----------------------------------------------------------------
            # INFERENCE
            # -----------------------------------------------------------------
            try:
                inference_frame = _prepare_inference_frame(color_frame)
                raw             = run_yolox_inference(model, exp, inference_frame, _device)

                if len(raw) > 0:
                    detections = sv.Detections(
                        xyxy       = raw[:, :4],
                        confidence = raw[:, 4] * raw[:, 5],  # obj_conf × class_conf
                        class_id   = raw[:, 6].astype(int),  # index 6, not 5
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

            # =================================================================
            # STEP 1 — Accumulate confidence votes per track per class.
            #
            # Each frame a track is visible, its detected class gets
            # confidence added to its vote bucket. get_best_class(tid)
            # returns whichever class has the highest total vote — this
            # is far more stable than locking a class on first detection.
            #
            # box-Sedr (index 0) and any unknown labels not in CLASS_WEIGHTS
            # are silently skipped here — they never accumulate votes.
            # =================================================================
            for tid, cid, conf in zip(
                detections.tracker_id,
                detections.class_id,
                detections.confidence,
            ):
                if tid is None:
                    continue
                class_name = CLASS_NAMES.get(int(cid), str(cid))
                if class_name in CLASS_WEIGHTS:
                    track_class_votes[tid][class_name] += float(conf)


            # =================================================================
            # RL FRAME CAPTURE — save low-confidence frames near the count line
            #
            # Triggers when:
            #   1. Object centroid is within RL_LINE_PROXIMITY_PX of CROSS_LINE_X
            #   2. Confidence is below RL_CONF_THRESHOLD
            # Saves raw color frame with label + confidence text overlay.
            # =================================================================
            for xyxy, tid, cid, conf in zip(
                detections.xyxy,
                detections.tracker_id,
                detections.class_id,
                detections.confidence,
            ):
                if tid is None:
                    continue

                cx = int(_box_centroid(xyxy)[0])

                # Check proximity to count line
                if abs(cx - CROSS_LINE_X) <= RL_LINE_PROXIMITY_PX:
                    # Check low confidence
                    if conf < RL_CONF_THRESHOLD:
                        label_name = CLASS_NAMES.get(int(cid), "unknown")
                        _save_rl_frame(
                            color_frame=color_frame,
                            session_id=session_id,
                            transaction_id=transaction_id,
                            label=label_name,
                            confidence=float(conf),
                        )

            # =================================================================
            # STEP 2 — Build labels for annotation overlay.
            #
            # Uses get_best_class(tid) so the displayed label is always the
            # voted winner, not the raw per-frame YOLOX output.
            # Falls back to CLASS_NAMES lookup if no votes yet for that tid.
            # =================================================================
            labels = []
            for tid, cid, conf in zip(
                detections.tracker_id,
                detections.class_id,
                detections.confidence,
            ):
                if tid is None:
                    labels.append("UNK")
                    continue
                best_name = get_best_class(tid) or CLASS_NAMES.get(int(cid), "UNK")
                labels.append(f"{best_name} {conf:.2f} ID:{tid}")

            # =================================================================
            # STEP 3 — Annotate (always on color frame)
            # =================================================================
            annotated_color = box_annotator.annotate(
                color_frame.copy(), detections
            )
            annotated_color = label_annotator.annotate(
                annotated_color, detections, labels
            )

            # 1 white vertical count line
            cv2.line(
                annotated_color,
                (CROSS_LINE_X, 0), (CROSS_LINE_X, FRAME_HEIGHT),
                (255, 255, 255), 3,
            )
            cv2.putText(
                annotated_color, "COUNT LINE",
                (CROSS_LINE_X + 5, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
            )

            # Single count bar bottom-left
            count_text = " | ".join(f"{k}:{v}" for k, v in counts.items())
            cv2.putText(
                annotated_color,
                count_text,
                (10, FRAME_HEIGHT - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
            )

            # Frame written to disk
            video_write_frame = (
                _make_save_frame(annotated_color)
                if _SAVE_DETECTED_VIDEO_GRAY
                else annotated_color
            )

            # =================================================================
            # STEP 4 — Single-line counting
            #
            # CLASS_WEIGHTS is the gate — only labels from BOX_CLASSES and
            # BALE_CLASSES in app.properties will trigger a count.
            #
            # When a label crosses the line, update_counts() is called once.
            # session.py.update_counts() will:
            #   - increment box or bale by the amount defined in BOX_CLASSES
            #     or BALE_CLASSES (e.g. sbale increments bale by 2)
            #   - increment trolley once per 3-second window automatically
            # Trolley is never in CLASS_WEIGHTS — handled entirely in session.py
            # =================================================================
            for xyxy, tid in zip(
                detections.xyxy,
                detections.tracker_id,
            ):
                if tid is None:
                    continue

                cx = int(_box_centroid(xyxy)[0])

                if tid in prev_x:
                    old_cx = prev_x[tid]

                    crossed = (
                        old_cx < CROSS_LINE_X <= cx
                        if CROSS_DIRECTION == "right"
                        else old_cx > CROSS_LINE_X >= cx
                    )

                    if crossed and tid not in counted_ids:
                        best_class = get_best_class(tid)

                        # If no votes have accumulated yet for this track,
                        # skip — better to miss one count than count wrong.
                        if best_class is None:
                            prev_x[tid] = cx
                            continue

                        # Gate: only count labels defined in app.properties
                        # BOX_CLASSES or BALE_CLASSES. Trolley, box-Sedr, and
                        # unknown labels are silently skipped.
                        if best_class in CLASS_WEIGHTS:
                            counted_ids.add(tid)

                            save_frame = (
                                _make_save_frame(annotated_color)
                                if _SAVE_DETECTED_FRAME_GRAY
                                else annotated_color
                            )

                            # Call update_counts ONCE — session.py handles
                            # the actual increment amount via BOX_CLASSES /
                            # BALE_CLASSES maps (e.g. sbale adds 2 to bale)
                            counts = session_manager.update_counts(
                                session_id,
                                best_class,
                                frame=save_frame,
                            )

                            logger.info(
                                Messages.get(
                                    "DETECTION.CROSSING.001.INFO",
                                    session_id=session_id,
                                    object_id=tid,
                                    label=best_class,
                                    counts=counts,
                                )
                            )

                prev_x[tid] = cx

            # =================================================================
            # STEP 5 — Write frame + update session counts
            # =================================================================
            session_manager.video_saver.write_frame(
                session_id, video_write_frame
            )
            session_manager.set_counts(session_id, counts)

            # =================================================================
            # STEP 6 — GUI: lazy window creation + imshow
            # Window is created on the first real frame — stays responsive.
            # imshow always shows the color annotated frame.
            # =================================================================
            if ENABLE_GUI and gui_available():

                if win is None:
                    try:
                        win = f"Detection-{session_id}"
                        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
                        cv2.resizeWindow(win, FRAME_WIDTH, FRAME_HEIGHT)
                        cv2.moveWindow(win, 0, 0)
                        logger.debug(
                            Messages.get(
                                "CAMERA.GUI.001.DEBUG", session_id=session_id
                            )
                        )
                    except Exception:
                        logger.exception(
                            Messages.get(
                                "CAMERA.GUI.002.ERROR", session_id=session_id
                            )
                        )
                        win = None

                if win is not None:
                    try:
                        cv2.imshow(win, annotated_color)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            logger.info(
                                Messages.get(
                                    "CAMERA.GUI.003.INFO", session_id=session_id
                                )
                            )
                            session_manager.stop_session(session_id)
                            break
                    except Exception:
                        logger.exception(
                            Messages.get(
                                "CAMERA.GUI.004.ERROR", session_id=session_id
                            )
                        )

            await asyncio.sleep(ASYNC_SLEEP_TIME)

        # ── End of loop ───────────────────────────────────────────────────
        cap.release()

        if win is not None:
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
                "DETECTION.EXCEPTION.001.ERROR", session_id=session_id
            )
        )
        mqtt_push_error(
            session_id=session_id,
            transaction_id=transaction_id,
            error_code="DETECTION_EXCEPTION",
            message="Unexpected detection error",
            severity="high",
        )

        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

        if win is not None:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

        session_manager.stop_session(session_id)