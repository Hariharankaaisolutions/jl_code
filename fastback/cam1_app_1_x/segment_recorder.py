# segment_recorder.py — FFmpeg Segment Recorder
# ===============================================
# Records RTMP stream into 10-minute .mp4 segments
# Segments saved to: video/YYYY-MM-DD/raw/
# One recorder per session/transaction
# ===============================================

import os
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional
from jl_logger import get_logger

logger = get_logger("SEGMENT_REC")

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

_props               = _load_props()
VIDEO_BASE_DIR       = _props.get("VIDEO_BASE_DIR",
                           "/opt/secure_ai/fastback/cam1_app_1_x/video")
SEGMENT_DURATION     = int(_props.get("SEGMENT_DURATION_SECS", "600"))
RTMP_INPUT_URL       = _props.get("RTMP_INPUT_URL", "rtmp://localhost/live/cam_1")
SEGMENT_MIN_SIZE     = int(_props.get("SEGMENT_MIN_SIZE_BYTES", "102400"))

# ─────────────────────────────────────────────────
# Active recorders registry
# ─────────────────────────────────────────────────
_recorders: dict = {}  # transaction_id → SegmentRecorder

# ─────────────────────────────────────────────────
# SegmentRecorder
# ─────────────────────────────────────────────────
class SegmentRecorder:
    """
    Records RTMP stream into fixed-duration .mp4 segments using FFmpeg.
    Segments named: <transaction_id>_seg<NNN>.mp4
    """

    def __init__(self, transaction_id: str, cam: str = "cam_1"):
        self.transaction_id = transaction_id
        self.cam            = cam
        self._stop_event    = threading.Event()
        self._thread:  Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None

        # Build output directory
        date_str   = datetime.now().strftime("%Y-%m-%d")
        self.raw_dir = os.path.join(VIDEO_BASE_DIR, date_str, "raw")
        os.makedirs(self.raw_dir, exist_ok=True)

        # Segment pattern: tx_abc123_seg000.mp4, tx_abc123_seg001.mp4 ...
        self.segment_pattern = os.path.join(
            self.raw_dir,
            f"{transaction_id}_seg%03d.mp4"
        )
        self.date_dir = os.path.join(VIDEO_BASE_DIR, date_str)

    def start(self):
        self._thread = threading.Thread(
            target=self._run,
            name=f"seg_rec_{self.transaction_id[:8]}",
            daemon=True
        )
        self._thread.start()
        logger.info(
            f"Segment recorder started → "
            f"tx={self.transaction_id[:8]} "
            f"dir={self.raw_dir} "
            f"segment={SEGMENT_DURATION}s"
        )

    def stop(self):
        self._stop_event.set()
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=10)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        if self._thread:
            self._thread.join(timeout=15)
        logger.info(f"Segment recorder stopped → tx={self.transaction_id[:8]}")

    def get_raw_dir(self) -> str:
        return self.raw_dir

    def get_date_dir(self) -> str:
        return self.date_dir

    def get_segments(self) -> list:
        """Return list of completed segment paths in order."""
        try:
            files = sorted([
                os.path.join(self.raw_dir, f)
                for f in os.listdir(self.raw_dir)
                if f.startswith(self.transaction_id) and f.endswith(".mp4")
            ])
            return files
        except Exception:
            return []

    def _run(self):
        """FFmpeg segment recording loop."""
        # Build FFmpeg command
        cmd = [
            "ffmpeg",
            "-i", RTMP_INPUT_URL,
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(SEGMENT_DURATION),
            "-segment_format", "mp4",
            "-reset_timestamps", "1",
            "-strftime", "0",
            "-y",
            self.segment_pattern
        ]

        logger.info(
            f"FFmpeg segment recorder starting → "
            f"input={RTMP_INPUT_URL} "
            f"output={self.segment_pattern}"
        )

        retry_count = 0
        max_retries = 10

        while not self._stop_event.is_set() and retry_count < max_retries:
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                _, stderr = self._process.communicate()

                if self._stop_event.is_set():
                    break

                # FFmpeg exited unexpectedly
                rc = self._process.returncode
                err_msg = stderr.decode("utf-8", errors="replace")[-300:] \
                          if stderr else ""
                logger.warning(
                    f"FFmpeg segment recorder exited rc={rc} "
                    f"tx={self.transaction_id[:8]} "
                    f"retry={retry_count}/{max_retries} "
                    f"err={err_msg}"
                )
                retry_count += 1
                time.sleep(3)

            except Exception as e:
                logger.error(
                    f"Segment recorder error: {e} "
                    f"tx={self.transaction_id[:8]}",
                    exc_info=True
                )
                retry_count += 1
                time.sleep(3)

        if retry_count >= max_retries:
            logger.error(
                f"Segment recorder gave up after {max_retries} retries "
                f"tx={self.transaction_id[:8]}"
            )


# ─────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────
def start_segment_recorder(transaction_id: str, cam: str = "cam_1") -> str:
    """Start segment recorder. Returns raw_dir path."""
    rec = SegmentRecorder(transaction_id, cam)
    _recorders[transaction_id] = rec
    rec.start()
    return rec.get_raw_dir()

def stop_segment_recorder(transaction_id: str):
    """Stop segment recorder."""
    rec = _recorders.pop(transaction_id, None)
    if rec:
        rec.stop()
        return rec
    return None

def get_recorder(transaction_id: str) -> Optional[SegmentRecorder]:
    return _recorders.get(transaction_id)
