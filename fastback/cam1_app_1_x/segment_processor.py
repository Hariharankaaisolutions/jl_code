# segment_processor.py — Segment MOG2 + YOLOX Processor
# =======================================================
# Watches for completed segments, runs MOG2+YOLOX on each,
# saves annotated video, accumulates counts to DB.
# Processes segment N while segment N+1 is being recorded.
# =======================================================

import os
import cv2
import time
import threading
import numpy as np
from datetime import datetime
from typing import Optional, Callable
from jl_logger import get_logger
from daily_counts_db import upsert_daily_counts

logger = get_logger("SEG_PROC")

# ─────────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────────
_PROPS_FILE = os.path.join(os.path.dirname(__file__), "app.properties")

def _load_props() -> dict:
    props = {}
    try:
        with open(_PROPS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
    except Exception:
        pass
    return props

_props                = _load_props()
VIDEO_BASE_DIR        = _props.get("VIDEO_BASE_DIR",
                            "/opt/secure_ai/fastback/cam1_app_1_x/video")
SEGMENT_MIN_SIZE      = int(_props.get("SEGMENT_MIN_SIZE_BYTES",   "102400"))
SEGMENT_WATCHER_POLL  = int(_props.get("SEGMENT_WATCHER_POLL_SECS", "5"))
SEGMENT_DURATION      = int(_props.get("SEGMENT_DURATION_SECS",    "600"))
MOG2_THRESHOLD        = int(_props.get("MOG2_THRESHOLD",            "500"))
MOG2_HISTORY          = int(_props.get("MOG2_HISTORY",              "500"))
MOG2_VAR_THRESHOLD    = int(_props.get("MOG2_VAR_THRESHOLD",        "16"))
CONF_THRES            = float(_props.get("CONF_THRES",              "0.4"))
IOU_THRES             = float(_props.get("IOU_THRES",               "0.45"))
CROSS_LINE_X          = int(_props.get("CROSS_LINE_X",              "200"))
CROSS_DIRECTION       = _props.get("CROSS_DIRECTION",               "left")
INF_FPS               = int(_props.get("INFERRED_VIDEO_FPS",        "15"))
INF_W                 = int(_props.get("INFERRED_VIDEO_WIDTH",       "640"))
INF_H                 = int(_props.get("INFERRED_VIDEO_HEIGHT",      "640"))
CPU_THRESHOLD         = float(_props.get("INFERENCE_CPU_THRESHOLD", "80"))

# ─────────────────────────────────────────────────
# Active processors registry
# ─────────────────────────────────────────────────
_processors: dict = {}

# ─────────────────────────────────────────────────
# YOLOX model loader (shared)
# ─────────────────────────────────────────────────
_yolox_model = None
_model_lock  = threading.Lock()

def _get_yolox_model():
    global _yolox_model
    if _yolox_model is not None:
        return _yolox_model
    with _model_lock:
        if _yolox_model is not None:
            return _yolox_model
        try:
            import torch
            import importlib.util
            import sys

            base_dir   = os.path.dirname(__file__)
            exp_file   = os.path.join(base_dir, "YOLOX", "exps", "default", "yolox_s.py")
            model_path = os.path.join(base_dir, "jl_yolox_cam1.pth")

            # Add YOLOX to path
            yolox_path = os.path.join(base_dir, "YOLOX")
            if yolox_path not in sys.path:
                sys.path.insert(0, yolox_path)

            # Load exp from file
            spec = importlib.util.spec_from_file_location("yolox_exp", exp_file)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            exp = mod.Exp()
            exp.num_classes = 7
            exp.test_conf   = 0.01
            exp.nmsthre     = IOU_THRES
            exp.test_size   = (640, 640)

            device = "cuda:0" if torch.cuda.is_available() else "cpu"
            logger.info(f"Loading YOLOX model → device={device} model={model_path}")

            ckpt  = torch.load(model_path, map_location=device, weights_only=False)
            model = exp.get_model().to(device)
            model.eval()
            model.load_state_dict(ckpt.get("model", ckpt))
            if device == "cuda:0":
                model = model.half()

            _yolox_model = (model, exp, device)
            logger.info(f"YOLOX model loaded → device={device} classes={exp.num_classes}")
            return _yolox_model

        except Exception as e:
            logger.error(f"YOLOX model load failed: {e}", exc_info=True)
            return None


# ─────────────────────────────────────────────────
# Segment Processor
# ─────────────────────────────────────────────────
class SegmentProcessor:
    """
    Watches raw/ dir for completed segments.
    Processes each with MOG2+YOLOX.
    Saves annotated video to inferred/.
    Accumulates counts.
    """

    def __init__(
        self,
        raw_dir:        str,
        date_dir:       str,
        session_id:     str,
        transaction_id: str,
        cam:            str = "cam_1",
        on_count:       Optional[Callable] = None,
    ):
        self.raw_dir        = raw_dir
        self.date_dir       = date_dir
        self.session_id     = session_id
        self.transaction_id = transaction_id
        self.cam            = cam
        self.on_count       = on_count

        self._stop_event       = threading.Event()
        self._thread:  Optional[threading.Thread] = None
        self._processed:  set  = set()   # segments already processed
        self._pending:    list = []      # segments queued
        self._done_event       = threading.Event()  # all segments processed

        # Counts
        self.counts = {"box": 0, "bale": 0, "trolley": 0, "bag": 0}
        self.total_frames   = 0
        self.motion_frames  = 0
        self.inferred_segs  = 0
        self.failed_segs    = 0

        # Output dir
        self.inferred_dir = os.path.join(date_dir, "inferred")
        os.makedirs(self.inferred_dir, exist_ok=True)

    def start(self):
        self._thread = threading.Thread(
            target=self._run,
            name=f"seg_proc_{self.transaction_id[:8]}",
            daemon=True
        )
        self._thread.start()
        logger.info(
            f"Segment processor started → "
            f"tx={self.transaction_id[:8]} "
            f"raw={self.raw_dir}"
        )

    def stop(self, drain: bool = True):
        """Stop watcher. If drain=True wait for pending segments to finish."""
        self._stop_event.set()
        if drain:
            logger.info(
                f"Draining remaining segments → "
                f"tx={self.transaction_id[:8]} "
                f"pending={len(self._pending)}"
            )
            if self._thread:
                self._thread.join(timeout=3600)  # max 1 hour drain
        else:
            if self._thread:
                self._thread.join(timeout=30)
        logger.info(
            f"Segment processor stopped → "
            f"tx={self.transaction_id[:8]} "
            f"inferred={self.inferred_segs} "
            f"failed={self.failed_segs} "
            f"counts={self.counts}"
        )

    def get_inferred_segments(self) -> list:
        """Return list of completed inferred segment paths."""
        try:
            return sorted([
                os.path.join(self.inferred_dir, f)
                for f in os.listdir(self.inferred_dir)
                if f.startswith(self.transaction_id) and f.endswith("_inf.mp4")
            ])
        except Exception:
            return []

    def is_done(self) -> bool:
        return self._done_event.is_set()

    # ─────────────────────────────────────────────
    # Main loop
    # ─────────────────────────────────────────────
    def _run(self):
        logger.info(f"Segment watcher loop started → tx={self.transaction_id[:8]}")

        while True:
            # Scan for new completed segments
            try:
                self._scan_for_new_segments()
            except Exception as e:
                logger.error(f"Segment scan error: {e}", exc_info=True)

            # Process next pending segment
            if self._pending:
                seg_path = self._pending.pop(0)
                try:
                    self._process_segment(seg_path)
                except Exception as e:
                    logger.error(
                        f"Segment process error: {e} "
                        f"seg={os.path.basename(seg_path)}",
                        exc_info=True
                    )
                    self.failed_segs += 1

            # Check if we should stop
            if self._stop_event.is_set() and not self._pending:
                # Final scan — pick up any last segments
                try:
                    self._scan_for_new_segments()
                except Exception:
                    pass
                if self._pending:
                    continue  # drain remaining
                break

            time.sleep(SEGMENT_WATCHER_POLL)

        self._done_event.set()
        logger.info(
            f"Segment processor loop ended → "
            f"tx={self.transaction_id[:8]} "
            f"total_frames={self.total_frames} "
            f"motion_frames={self.motion_frames} "
            f"inferred={self.inferred_segs} "
            f"failed={self.failed_segs} "
            f"counts={self.counts}"
        )

    def _scan_for_new_segments(self):
        """Find completed segments not yet processed."""
        if not os.path.exists(self.raw_dir):
            return

        all_segs = sorted([
            os.path.join(self.raw_dir, f)
            for f in os.listdir(self.raw_dir)
            if f.startswith(self.transaction_id) and f.endswith(".mp4")
        ])

        for seg in all_segs:
            if seg in self._processed:
                continue
            if seg in self._pending:
                continue

            # Skip the last segment if recording is still active
            # (it may be partially written)
            is_last = seg == all_segs[-1]
            if is_last and not self._stop_event.is_set():
                # Check if it's old enough to be complete
                try:
                    age = time.time() - os.path.getmtime(seg)
                    size = os.path.getsize(seg)
                    # If last segment is older than segment_duration + 30s
                    # and size > min — it's complete (session ended)
                    if age < SEGMENT_DURATION + 30 and size > SEGMENT_MIN_SIZE:
                        continue  # still being written
                except Exception:
                    continue

            # Check minimum size
            try:
                size = os.path.getsize(seg)
                if size < SEGMENT_MIN_SIZE:
                    logger.warning(
                        f"Segment too small ({size} bytes) — skipping: "
                        f"{os.path.basename(seg)}"
                    )
                    self._processed.add(seg)
                    continue
            except Exception:
                continue

            logger.info(
                f"New segment queued → "
                f"{os.path.basename(seg)} "
                f"size={size/1024/1024:.1f}MB"
            )
            self._pending.append(seg)
            self._processed.add(seg)

    # ─────────────────────────────────────────────
    # Process one segment
    # ─────────────────────────────────────────────
    def _process_segment(self, seg_path: str):
        seg_name = os.path.basename(seg_path)
        logger.info(f"Processing segment → {seg_name}")

        # Output path
        inf_name = seg_name.replace(".mp4", "_inf.mp4")
        inf_path = os.path.join(self.inferred_dir, inf_name)

        cap    = None
        writer = None

        try:
            # ── Open video ──────────────────────────────
            cap = cv2.VideoCapture(seg_path)
            if not cap.isOpened():
                logger.error(f"Cannot open segment: {seg_name}")
                self.failed_segs += 1
                return

            fps    = cap.get(cv2.CAP_PROP_FPS) or INF_FPS
            width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or INF_W
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or INF_H
            total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            logger.info(
                f"Segment opened → {seg_name} "
                f"fps={fps:.1f} size={width}x{height} frames={total}"
            )

            # ── Output writer ────────────────────────────
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(inf_path, fourcc, fps, (width, height))
            if not writer.isOpened():
                logger.error(f"Cannot create output writer: {inf_name}")
                self.failed_segs += 1
                return

            # ── Load exclusion zones ─────────────────────
            import json as _json
            _zone_path = os.path.join(os.path.dirname(__file__), "exclusion_zones.json")
            _zones = []
            if os.path.exists(_zone_path):
                with open(_zone_path) as _f:
                    _zones = _json.load(_f)
                logger.info(f"Exclusion zones loaded: {len(_zones)} zones")
            else:
                logger.warning("No exclusion_zones.json found — using full frame")

            # Build exclusion mask
            _excl_mask = np.ones((height, width), dtype=np.uint8) * 255
            for _zone in _zones:
                _pts = np.array(_zone, dtype=np.int32)
                cv2.fillPoly(_excl_mask, [_pts], 0)

            # CUDA stream
            _stream = cv2.cuda.Stream()

            # ── MOG2 background subtractor (GPU) ─────────
            try:
                mog2 = cv2.cuda.createBackgroundSubtractorMOG2(
                    history=MOG2_HISTORY,
                    varThreshold=MOG2_VAR_THRESHOLD,
                    detectShadows=True
                )
                use_gpu_mog2 = True
                logger.info("MOG2 running on GPU ✅")
            except Exception:
                mog2 = cv2.createBackgroundSubtractorMOG2(
                    history=MOG2_HISTORY,
                    varThreshold=MOG2_VAR_THRESHOLD,
                    detectShadows=False
                )
                use_gpu_mog2 = False
                logger.warning("MOG2 falling back to CPU")

            # ── Load YOLOX model ─────────────────────────
            model_data = _get_yolox_model()
            if model_data is None:
                logger.error("YOLOX model not available — skipping inference")
                self.failed_segs += 1
                return
            model, exp, device = model_data

            # ── Per-segment counts and tracking ─────────
            seg_counts   = {"box": 0, "bale": 0, "trolley": 0, "bag": 0}
            tracked      = {}   # track_id → last cx
            frame_num    = 0
            motion_count = 0
            consecutive_fail = 0
            max_consecutive_fail = 30

            import psutil
            import torch

            # ── Frame loop ───────────────────────────────
            while True:
                # CPU spike protection
                cpu = psutil.cpu_percent(interval=0.1)
                if cpu > CPU_THRESHOLD:
                    logger.warning(
                        f"CPU spike {cpu}% — pausing inference "
                        f"seg={seg_name} frame={frame_num}"
                    )
                    time.sleep(2.0)
                    continue

                # Read frame
                try:
                    ret, frame = cap.read()
                except Exception as e:
                    logger.error(
                        f"Frame read exception: {e} "
                        f"seg={seg_name} frame={frame_num}"
                    )
                    consecutive_fail += 1
                    if consecutive_fail >= max_consecutive_fail:
                        logger.warning(
                            f"Too many consecutive read failures "
                            f"({consecutive_fail}) — ending segment"
                        )
                        break
                    continue

                if not ret or frame is None:
                    consecutive_fail += 1
                    if consecutive_fail >= max_consecutive_fail:
                        logger.info(
                            f"End of segment reached → "
                            f"{seg_name} frames={frame_num}"
                        )
                        break
                    time.sleep(0.01)
                    continue

                consecutive_fail = 0
                frame_num += 1
                self.total_frames += 1

                # Resize if needed
                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height))

                # MOG2 motion check
                try:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    if use_gpu_mog2:
                        _gpu_gray = cv2.cuda_GpuMat()
                        _gpu_gray.upload(gray)
                        _gpu_mask = mog2.apply(_gpu_gray, -1, _stream)
                        fg_mask = _gpu_mask.download()
                    else:
                        fg_mask = mog2.apply(gray)

                    # Remove shadows
                    _, fg_mask = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)

                    # Morphological cleanup
                    _kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
                    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, _kernel)
                    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, _kernel)

                    # Apply exclusion zones
                    fg_filtered = cv2.bitwise_and(fg_mask, _excl_mask)

                    # Check contours
                    _contours, _ = cv2.findContours(fg_filtered,
                        cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    _significant = [c for c in _contours
                                   if cv2.contourArea(c) > 500]
                    has_motion = len(_significant) > 0

                except Exception as e:
                    logger.error(f"MOG2 error: {e} frame={frame_num}")
                    has_motion = True

                if not has_motion:
                    continue  # skip non-motion frames

                motion_count += 1
                self.motion_frames += 1

                # YOLOX inference
                try:
                    inf_frame, detections = self._run_yolox(
                        frame, model, exp, device
                    )
                except Exception as e:
                    logger.error(
                        f"YOLOX inference error: {e} "
                        f"seg={seg_name} frame={frame_num}"
                    )
                    writer.write(frame)
                    continue

                # Count crossing
                try:
                    new_counts = self._check_crossing(detections, tracked)
                    for k, v in new_counts.items():
                        seg_counts[k]    += v
                        self.counts[k]   += v
                except Exception as e:
                    logger.error(f"Crossing check error: {e} frame={frame_num}")

                # Draw exclusion zones on frame
                try:
                    for _z in _zones:
                        _zpts = np.array(_z, dtype=np.int32)
                        cv2.polylines(inf_frame, [_zpts], True, (0, 0, 255), 1)
                except Exception:
                    pass

                # Draw count line on frame
                try:
                    cv2.line(
                        inf_frame,
                        (CROSS_LINE_X, 0),
                        (CROSS_LINE_X, height),
                        (0, 255, 0), 2
                    )
                    y = 30
                    for cls, cnt in self.counts.items():
                        cv2.putText(
                            inf_frame,
                            f"{cls}: {cnt}",
                            (10, y),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (0, 255, 255), 2
                        )
                        y += 25
                except Exception as e:
                    logger.error(f"Draw error: {e}")
                    inf_frame = frame

                writer.write(inf_frame)

            # ── Segment done ─────────────────────────────
            logger.info(
                f"Segment complete → {seg_name} "
                f"frames={frame_num} motion={motion_count} "
                f"counts={seg_counts}"
            )

            # Save counts to DB
            try:
                upsert_daily_counts(
                    session_id=self.session_id,
                    transaction_id=self.transaction_id,
                    cam=self.cam,
                    box_count=self.counts.get("box", 0),
                    bale_count=self.counts.get("bale", 0),
                    trolley_count=self.counts.get("trolley", 0),
                    bag_count=self.counts.get("bag", 0),
                )
            except Exception as e:
                logger.error(f"DB upsert error: {e}", exc_info=True)

            # Callback
            if self.on_count:
                try:
                    self.on_count(self.session_id, self.counts.copy())
                except Exception as e:
                    logger.error(f"on_count callback error: {e}")

            self.inferred_segs += 1

        except Exception as e:
            logger.error(
                f"Unexpected error processing segment {seg_name}: {e}",
                exc_info=True
            )
            self.failed_segs += 1

        finally:
            if cap:
                try:
                    cap.release()
                except Exception:
                    pass
            if writer:
                try:
                    writer.release()
                except Exception:
                    pass

    # ─────────────────────────────────────────────
    # YOLOX inference
    # ─────────────────────────────────────────────
    def _run_yolox(self, frame, model, exp, device):
        import torch
        from yolox.data.data_augment import ValTransform
        from yolox.utils import postprocess

        # Convert to grayscale→3ch (same as yolox_processor)
        gray      = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_rgb = cv2.merge([gray, gray, gray])

        preproc   = ValTransform(legacy=False)
        img, _    = preproc(frame_rgb, None, exp.test_size)
        h, w      = frame_rgb.shape[:2]
        ratio     = min(exp.test_size[0] / h, exp.test_size[1] / w)
        tensor    = torch.from_numpy(img).unsqueeze(0).to(device)
        if device == "cuda:0":
            tensor = tensor.half()
        else:
            tensor = tensor.float()

        with torch.no_grad():
            outputs = model(tensor)
            outputs = postprocess(
                outputs, exp.num_classes, exp.test_conf, exp.nmsthre
            )

        CLASS_NAMES = {0: "box-Sedr", 1: "bale", 2: "box",
                       3: "fbale",    4: "sbale", 5: "tbale_a", 6: "tbale_b"}

        detections = []
        if outputs[0] is not None:
            dets = outputs[0].cpu().numpy()
            dets[:, 0:4] /= ratio
            for det in dets:
                x1, y1, x2, y2 = det[0:4]
                conf    = float(det[4] * det[5])
                cls_id  = int(det[6])
                cls     = CLASS_NAMES.get(cls_id, str(cls_id))
                if conf < CONF_THRES:
                    continue
                cx = int((x1 + x2) / 2)
                cy = int((y1 + y2) / 2)
                detections.append({
                    "x1": int(x1), "y1": int(y1),
                    "x2": int(x2), "y2": int(y2),
                    "cx": cx, "cy": cy,
                    "conf": conf,
                    "cls_id": cls_id,
                    "cls": cls,
                })
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)),
                              (0, 200, 255), 2)
                cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
                cv2.putText(frame, f"{cls} {conf:.2f}",
                           (int(x1), int(y1)-5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,200,255), 1)

        return frame, detections

    # ─────────────────────────────────────────────
    # Crossing detection
    # ─────────────────────────────────────────────
    def _check_crossing(self, detections, tracked):
        # Map model classes to count categories
        CLASS_MAP = {
            "box-Sedr": "box",
            "bale":     "bale",
            "box":      "box",
            "fbale":    "bale",
            "sbale":    "bale",
            "tbale_a":  "bale",
            "tbale_b":  "bale",
        }
        new_counts = {"box": 0, "bale": 0, "trolley": 0, "bag": 0}

        for i, det in enumerate(detections):
            cx     = det["cx"]
            cls    = CLASS_MAP.get(det.get("cls", "box"), "box")
            tid    = i  # simple index as track id

            if tid in tracked:
                old_cx = tracked[tid]
                crossed = False
                if CROSS_DIRECTION == "left":
                    crossed = old_cx > CROSS_LINE_X >= cx
                else:
                    crossed = old_cx < CROSS_LINE_X <= cx

                if crossed:
                    new_counts[cls] = new_counts.get(cls, 0) + 1
                    logger.info(
                        f"COUNT: {cls} crossed line "
                        f"({old_cx}→{cx}) total={self.counts[cls]+new_counts[cls]}"
                    )

            tracked[tid] = cx

        return new_counts


# ─────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────
def start_segment_processor(
    raw_dir:        str,
    date_dir:       str,
    session_id:     str,
    transaction_id: str,
    cam:            str = "cam_1",
    on_count:       Optional[Callable] = None,
) -> SegmentProcessor:
    proc = SegmentProcessor(
        raw_dir=raw_dir,
        date_dir=date_dir,
        session_id=session_id,
        transaction_id=transaction_id,
        cam=cam,
        on_count=on_count,
    )
    _processors[transaction_id] = proc
    proc.start()
    return proc

def stop_segment_processor(transaction_id: str, drain: bool = True):
    proc = _processors.pop(transaction_id, None)
    if proc:
        proc.stop(drain=drain)
        return proc
    return None

def get_processor(transaction_id: str) -> Optional[SegmentProcessor]:
    return _processors.get(transaction_id)
