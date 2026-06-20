# yolox_processor.py — YOLOX Inference Processor (Thread 2)
# ===========================================================
# Reads frames from MOG2 buffer directory in order
# Checks CPU before each frame — pauses if CPU > threshold
# Runs YOLOX inference on motion frames
# Updates counts, DB, MQTT on detections
# Deletes buffer file immediately after processing
# Drains buffer completely before stopping at 18:00
# ===========================================================

import os
import cv2
import sys
import time
import asyncio
import threading
import numpy as np
from datetime import datetime
from typing import Optional
import psutil

from jl_logger import get_logger, log_separator
from system_metrics import is_cpu_spike, is_gpu_spike
from daily_counts_db import upsert_daily_counts, upsert_mog2_log

logger = get_logger("INFERENCE")

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

_props              = _load_props()
CPU_THRESHOLD       = float(_props.get("INFERENCE_CPU_THRESHOLD", "80"))
BUFFER_FORMAT       = _props.get("MOG2_BUFFER_FORMAT", "jpg")
FRAME_WIDTH         = int(_props.get("FRAME_WIDTH",  "640"))
FRAME_HEIGHT        = int(_props.get("FRAME_HEIGHT", "480"))
CONF_THRES          = float(_props.get("CONF_THRES", "0.4"))
IOU_THRES           = float(_props.get("IOU_THRES",  "0.45"))
MODEL_PATH          = _props.get("MODEL_PATH", "jl_yolox_cam1.pth")
EXP_FILE            = _props.get("EXP_FILE",
    "/opt/secure_ai/fastback/cam1_app_1_x/YOLOX/exps/default/yolox_s.py")
CROSS_LINE_X        = int(_props.get("CROSS_LINE_X",    "200"))
CROSS_DIRECTION     = _props.get("CROSS_DIRECTION",     "left")
_LOG_EVERY_N        = 100
_BUFFER_POLL_SECS   = 0.1   # how often to check buffer when empty
_CPU_RETRY_SECS     = 1.0   # how often to retry when CPU is high


# ─────────────────────────────────────────────────
# YOLOX model loader (singleton)
# ─────────────────────────────────────────────────
_model      = None
_exp        = None
_device     = None
_model_lock = threading.Lock()

def _load_model():
    global _model, _exp, _device
    with _model_lock:
        if _model is not None:
            return _model, _exp, _device

        import torch
        import importlib.util
        sys.path.insert(0, os.path.dirname(EXP_FILE))
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "YOLOX"))

        _device = "cuda:0" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading YOLOX model → device={_device} model={MODEL_PATH}")

        try:
            spec = importlib.util.spec_from_file_location("exp", EXP_FILE)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _exp = mod.Exp()
            _exp.num_classes = 7  # JL custom model

            model_full_path = os.path.join(os.path.dirname(__file__), MODEL_PATH)
            ckpt  = torch.load(model_full_path, map_location=_device, weights_only=False)
            _model = _exp.get_model().to(_device)
            _model.eval()
            _model.load_state_dict(ckpt["model"])

            logger.info(
                f"YOLOX model loaded → "
                f"device={_device} "
                f"classes={_exp.num_classes} "
                f"test_size={_exp.test_size} "
                f"conf={_exp.test_conf}"
            )
        except Exception as e:
            logger.error(f"YOLOX model load failed: {e}", exc_info=True)
            raise

        return _model, _exp, _device


# ─────────────────────────────────────────────────
# YOLOX inference
# ─────────────────────────────────────────────────
def _run_inference(frame_bgr: np.ndarray) -> list:
    """
    Run YOLOX inference on a BGR frame.
    Returns list of dicts: [{class_id, class_name, confidence, bbox}, ...]
    """
    import torch
    from yolox.data.data_augment import ValTransform
    from yolox.utils import postprocess

    model, exp, device = _load_model()

    try:
        # Prepare frame
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        frame_rgb = cv2.merge([frame_rgb, frame_rgb, frame_rgb])

        preproc    = ValTransform(legacy=False)
        img, _     = preproc(frame_rgb, None, exp.test_size)
        h, w       = frame_rgb.shape[:2]
        ratio      = min(exp.test_size[0] / h, exp.test_size[1] / w)
        tensor     = torch.from_numpy(img).unsqueeze(0).to(device).float()

        with torch.no_grad():
            outputs = model(tensor)
            outputs = postprocess(outputs, exp.num_classes, exp.test_conf, exp.nmsthre)

        if outputs[0] is None:
            return []

        dets = outputs[0].cpu().numpy()
        dets[:, 0:4] /= ratio

        CLASS_NAMES = {0: "box-Sedr", 1: "bale", 2: "box",
                       3: "fbale", 4: "sbale", 5: "tbale_a", 6: "tbale_b"}

        results = []
        for det in dets:
            x1, y1, x2, y2 = det[0:4]
            conf      = float(det[4] * det[5])
            class_id  = int(det[6])
            results.append({
                "class_id":   class_id,
                "class_name": CLASS_NAMES.get(class_id, str(class_id)),
                "confidence": round(conf, 4),
                "bbox":       [float(x1), float(y1), float(x2), float(y2)],
                "cx":         float((x1 + x2) / 2),
            })
        return results

    except Exception as e:
        logger.error(f"YOLOX inference error: {e}", exc_info=True)
        return []


# ─────────────────────────────────────────────────
# Crossing line check
# ─────────────────────────────────────────────────
def _crossed_line(prev_cx: float, curr_cx: float) -> bool:
    """Check if object crossed CROSS_LINE_X in CROSS_DIRECTION."""
    if CROSS_DIRECTION == "left":
        return prev_cx > CROSS_LINE_X >= curr_cx
    else:  # right
        return prev_cx < CROSS_LINE_X <= curr_cx


# ─────────────────────────────────────────────────
# YOLOXProcessor class
# ─────────────────────────────────────────────────
class YOLOXProcessor:
    """
    Reads MOG2 buffer files in order and runs YOLOX inference.
    Pauses when CPU > threshold. Resumes automatically.
    Drains buffer completely before stopping.

    Usage:
        proc = YOLOXProcessor(
            buffer_dir=".../mog2_buffer/2026-06-12/tx_id/",
            session_id="...",
            transaction_id="...",
            cam="cam_1",
            on_count=my_callback,
        )
        proc.start()
        proc.stop()
    """

    def __init__(
        self,
        buffer_dir:     str,
        session_id:     str,
        transaction_id: str,
        cam:            str = "cam_1",
        on_count=None,
    ):
        self.buffer_dir     = buffer_dir
        self.session_id     = session_id
        self.transaction_id = transaction_id
        self.cam            = cam
        self.on_count       = on_count  # callback(session_id, counts)

        # Counts
        self.counts = {"box": 0, "bale": 0, "trolley": 0, "bag": 0}

        # Track object centroids for crossing detection
        self._prev_centroids: dict = {}  # track_id → prev_cx (simplified)

        # Stats
        self.yolox_processed  = 0
        self.cpu_pauses       = 0
        self.inference_times  = []
        self._started_at: Optional[datetime] = None

        # Control
        self._stop_event  = threading.Event()
        self._drain_mode  = False  # True = drain buffer then stop
        self._thread: Optional[threading.Thread] = None

        logger.info(
            f"YOLOXProcessor created → "
            f"session={session_id[:8]} "
            f"tx={transaction_id[:8]} "
            f"cam={cam} "
            f"buffer={buffer_dir} "
            f"cpu_threshold={CPU_THRESHOLD}%"
        )

    # ─────────────────────────────────────────────
    # Start / Stop
    # ─────────────────────────────────────────────
    def start(self):
        """Start YOLOX processor thread."""
        if self._thread and self._thread.is_alive():
            logger.warning(
                f"YOLOXProcessor already running "
                f"tx={self.transaction_id[:8]}"
            )
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"yolox_{self.transaction_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        self._started_at = datetime.now()
        logger.info(
            f"YOLOXProcessor thread started → "
            f"tx={self.transaction_id[:8]}"
        )

    def stop(self, drain_first: bool = True):
        """
        Signal processor to stop.
        drain_first=True → finish all remaining buffer files before stopping.
        drain_first=False → stop immediately.
        """
        if drain_first:
            self._drain_mode = True
            remaining = self._count_buffer_files()
            logger.info(
                f"YOLOXProcessor drain mode → "
                f"tx={self.transaction_id[:8]} "
                f"remaining={remaining} frames to process"
            )
            # Wait for drain to complete (max 30 min)
            if self._thread:
                self._thread.join(timeout=1800)
        else:
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout=10)

        self._log_final_stats()
        logger.info(
            f"YOLOXProcessor stopped → "
            f"tx={self.transaction_id[:8]} "
            f"processed={self.yolox_processed} "
            f"cpu_pauses={self.cpu_pauses}"
        )

    def get_stats(self) -> dict:
        elapsed = 0.0
        if self._started_at:
            elapsed = (datetime.now() - self._started_at).total_seconds()
        avg_inf = (
            sum(self.inference_times) / len(self.inference_times)
            if self.inference_times else 0
        )
        return {
            "yolox_processed":  self.yolox_processed,
            "cpu_pauses":       self.cpu_pauses,
            "avg_inference_ms": round(avg_inf * 1000, 1),
            "elapsed_secs":     round(elapsed, 1),
            "counts":           self.counts.copy(),
        }

    # ─────────────────────────────────────────────
    # Internal run loop
    # ─────────────────────────────────────────────
    def _run(self):
        """Main YOLOX processing loop — runs in background thread."""
        log_separator("INFERENCE", f"YOLOX PROCESSOR STARTING tx={self.transaction_id[:8]}")

        # Pre-load model
        try:
            _load_model()
        except Exception as e:
            logger.error(f"Model load failed — processor cannot start: {e}", exc_info=True)
            return

        while True:
            # Check stop
            if self._stop_event.is_set():
                break

            # In drain mode — exit only when buffer is empty
            if self._drain_mode:
                remaining = self._count_buffer_files()
                if remaining == 0:
                    logger.info(
                        f"Buffer drained completely → "
                        f"tx={self.transaction_id[:8]} "
                        f"total_processed={self.yolox_processed}"
                    )
                    break

            # Get next buffer file
            next_file = self._get_next_file()
            if next_file is None:
                if self._drain_mode:
                    time.sleep(0.1)
                    continue
                time.sleep(_BUFFER_POLL_SECS)
                continue

            # CPU spike check — wait until CPU normalizes
            spike_logged = False
            while True:
                is_spike, cpu = is_cpu_spike()
                if not is_spike:
                    break
                if not spike_logged:
                    self.cpu_pauses += 1
                    logger.warning(
                        f"CPU spike={cpu:.1f}% >= {CPU_THRESHOLD}% — "
                        f"inference paused. "
                        f"Buffer pending={self._count_buffer_files()} frames"
                    )
                    spike_logged = True
                time.sleep(_CPU_RETRY_SECS)

            if spike_logged:
                is_spike, cpu = is_cpu_spike()
                logger.info(
                    f"CPU normalized={cpu:.1f}% — "
                    f"inference resuming. "
                    f"Total pauses={self.cpu_pauses}"
                )

            # Read frame
            try:
                frame = cv2.imread(next_file)
                if frame is None:
                    logger.warning(f"Could not read buffer frame: {next_file}")
                    self._delete_file(next_file)
                    continue
            except Exception as e:
                logger.error(f"Frame read error {next_file}: {e}", exc_info=True)
                self._delete_file(next_file)
                continue

            # Run inference
            t0 = time.time()
            try:
                detections = _run_inference(frame)
            except Exception as e:
                logger.error(f"Inference error: {e}", exc_info=True)
                self._delete_file(next_file)
                continue

            inf_time = time.time() - t0
            self.inference_times.append(inf_time)
            if len(self.inference_times) > 500:
                self.inference_times = self.inference_times[-500:]

            self.yolox_processed += 1

            # Process detections
            if detections:
                self._process_detections(detections, next_file)

            # Delete processed buffer file immediately
            self._delete_file(next_file)

            # Log stats every N frames
            if self.yolox_processed % _LOG_EVERY_N == 0:
                avg_inf = (
                    sum(self.inference_times[-50:]) /
                    min(len(self.inference_times), 50)
                ) * 1000
                logger.info(
                    f"YOLOX stats → "
                    f"processed={self.yolox_processed} "
                    f"avg_inf={avg_inf:.1f}ms "
                    f"cpu_pauses={self.cpu_pauses} "
                    f"counts={self.counts} "
                    f"buffer_pending={self._count_buffer_files()}"
                )
                self._flush_db_stats()

        log_separator("INFERENCE", f"YOLOX PROCESSOR ENDED tx={self.transaction_id[:8]}")

    # ─────────────────────────────────────────────
    # Detection processing
    # ─────────────────────────────────────────────
    def _process_detections(self, detections: list, frame_path: str):
        """Process detections — update counts on line crossing."""
        CLASS_WEIGHTS = {
            "box":     1, "bale":    1, "fbale":   1,
            "sbale":   2, "tbale_a": 2, "tbale_b": 2,
        }

        count_updated = False

        for det in detections:
            class_name = det["class_name"]
            conf       = det["confidence"]
            cx         = det["cx"]

            if class_name not in CLASS_WEIGHTS:
                continue

            tid = det.get("track_id", id(det))

            # Check crossing
            prev_cx = self._prev_centroids.get(tid)
            if prev_cx is not None:
                if _crossed_line(prev_cx, cx):
                    weight = CLASS_WEIGHTS[class_name]

                    if class_name == "box":
                        self.counts["box"] += weight
                    else:
                        self.counts["bale"] += weight

                    count_updated = True
                    logger.info(
                        f"COUNT → class={class_name} "
                        f"weight={weight} "
                        f"conf={conf:.3f} "
                        f"cx={cx:.0f}→{prev_cx:.0f} "
                        f"counts={self.counts} "
                        f"tx={self.transaction_id[:8]}"
                    )

            self._prev_centroids[tid] = cx

        if count_updated:
            # Update daily counts DB
            upsert_daily_counts(
                session_id=self.session_id,
                transaction_id=self.transaction_id,
                cam=self.cam,
                box_count=self.counts["box"],
                bale_count=self.counts["bale"],
                trolley_count=self.counts["trolley"],
                bag_count=self.counts["bag"],
            )
            # Fire callback (MQTT push etc)
            if self.on_count:
                try:
                    self.on_count(self.session_id, self.counts.copy())
                except Exception as e:
                    logger.error(f"on_count callback error: {e}", exc_info=True)

    # ─────────────────────────────────────────────
    # Buffer file helpers
    # ─────────────────────────────────────────────
    def _get_next_file(self) -> Optional[str]:
        """Get oldest buffer file (lowest frame index = oldest)."""
        try:
            files = sorted([
                f for f in os.listdir(self.buffer_dir)
                if f.endswith(f".{BUFFER_FORMAT}")
            ])
            if files:
                return os.path.join(self.buffer_dir, files[0])
            return None
        except Exception:
            return None

    def _count_buffer_files(self) -> int:
        try:
            return sum(
                1 for f in os.listdir(self.buffer_dir)
                if f.endswith(f".{BUFFER_FORMAT}")
            )
        except Exception:
            return 0

    def _delete_file(self, path: str):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"Could not delete buffer file {path}: {e}")

    # ─────────────────────────────────────────────
    # DB flush
    # ─────────────────────────────────────────────
    def _flush_db_stats(self):
        try:
            stats = self.get_stats()
            upsert_mog2_log(
                session_id=self.session_id,
                transaction_id=self.transaction_id,
                cam=self.cam,
                yolox_processed=self.yolox_processed,
                cpu_pauses=self.cpu_pauses,
                avg_inference_ms=stats["avg_inference_ms"],
            )
        except Exception as e:
            logger.error(f"YOLOXProcessor flush_db_stats failed: {e}", exc_info=True)

    def _log_final_stats(self):
        stats = self.get_stats()
        logger.info(
            f"YOLOX final stats → "
            f"tx={self.transaction_id[:8]} "
            f"processed={stats['yolox_processed']} "
            f"avg_inf={stats['avg_inference_ms']}ms "
            f"cpu_pauses={stats['cpu_pauses']} "
            f"elapsed={stats['elapsed_secs']}s "
            f"final_counts={stats['counts']}"
        )
        self._flush_db_stats()


# ─────────────────────────────────────────────────
# Active processors registry
# ─────────────────────────────────────────────────
_processors: dict[str, YOLOXProcessor] = {}
_proc_lock = threading.Lock()

def start_yolox_processor(
    buffer_dir:     str,
    session_id:     str,
    transaction_id: str,
    cam:            str = "cam_1",
    on_count=None,
) -> Optional[YOLOXProcessor]:
    """Create and start a YOLOX processor for a session."""
    try:
        proc = YOLOXProcessor(
            buffer_dir=buffer_dir,
            session_id=session_id,
            transaction_id=transaction_id,
            cam=cam,
            on_count=on_count,
        )
        proc.start()
        with _proc_lock:
            _processors[transaction_id] = proc
        logger.info(f"YOLOXProcessor registered → tx={transaction_id[:8]}")
        return proc
    except Exception as e:
        logger.error(f"start_yolox_processor failed: {e}", exc_info=True)
        return None

def stop_yolox_processor(transaction_id: str, drain_first: bool = True) -> dict:
    """Stop and remove a YOLOX processor. Returns final stats."""
    with _proc_lock:
        proc = _processors.pop(transaction_id, None)
    if proc:
        proc.stop(drain_first=drain_first)
        stats = proc.get_stats()
        logger.info(
            f"YOLOXProcessor removed → "
            f"tx={transaction_id[:8]} "
            f"final={stats}"
        )
        return stats
    logger.warning(
        f"stop_yolox_processor: no processor found "
        f"for tx={transaction_id[:8]}"
    )
    return {}

