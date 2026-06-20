"""
cam1/recording/segment_recorder.py — FFmpeg Segment Recorder
=============================================================
Records RTMP stream into fixed-duration .mp4 segments.
One recorder per session. Retries on failure.
Max 80 lines. One responsibility: record segments.
"""

import os
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional

from core.config import get, getint
from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("REC")

RTMP_INPUT   = get("CAM2_RTMP_INPUT",   "rtmp://localhost/live/cam_1")
VIDEO_DIR    = get("CAM2_VIDEO_BASE_DIR", "/opt/secure_ai/cam2/video")
SEG_DURATION = getint("SEGMENT_DURATION_SECS", 600)
MAX_RETRIES  = 10


class SegmentRecorder:
    """Records RTMP stream into 10-min segments using FFmpeg."""

    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id
        self._stop          = threading.Event()
        self._process:      Optional[subprocess.Popen] = None
        self._thread:       Optional[threading.Thread] = None
        date_str            = datetime.now().strftime("%Y-%m-%d")
        self.raw_dir        = os.path.join(VIDEO_DIR, date_str, "raw")
        self.date_dir       = os.path.join(VIDEO_DIR, date_str)
        os.makedirs(self.raw_dir, exist_ok=True)
        self.pattern        = os.path.join(
            self.raw_dir, f"{transaction_id}_seg%03d.mp4")

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True,
            name=f"rec_{self.transaction_id[:8]}")
        self._thread.start()
        logger.info(LOG("REC.002.INFO",
            tx_id=self.transaction_id[:8],
            dir=self.raw_dir, duration=SEG_DURATION))

    def stop(self) -> None:
        self._stop.set()
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
        logger.info(LOG("REC.003.INFO", tx_id=self.transaction_id[:8]))

    def get_raw_dir(self)  -> str: return self.raw_dir
    def get_date_dir(self) -> str: return self.date_dir

    def get_segments(self) -> list:
        try:
            return sorted([
                os.path.join(self.raw_dir, f)
                for f in os.listdir(self.raw_dir)
                if f.startswith(self.transaction_id) and f.endswith(".mp4")
            ])
        except Exception:
            return []

    def _run(self) -> None:
        cmd = [
            "ffmpeg", "-i", RTMP_INPUT,
            "-c", "copy", "-f", "segment",
            "-segment_time", str(SEG_DURATION),
            "-segment_format", "mp4",
            "-reset_timestamps", "1",
            "-strftime", "0", "-y", self.pattern,
        ]
        logger.info(LOG("REC.001.INFO",
            tx_id=self.transaction_id[:8], input=RTMP_INPUT))
        retries = 0
        while not self._stop.is_set() and retries < MAX_RETRIES:
            try:
                self._process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                _, stderr = self._process.communicate()
                if self._stop.is_set():
                    break
                rc      = self._process.returncode
                err_msg = stderr.decode("utf-8", errors="replace")[-200:]
                logger.warning(LOG("REC.004.WARN",
                    rc=rc, retry=retries, error=err_msg,
                    tx_id=self.transaction_id[:8]))
                retries += 1
                time.sleep(3)
            except Exception as e:
                logger.error(LOG("DET.005.ERROR", error=e))
                retries += 1
                time.sleep(3)
        if retries >= MAX_RETRIES:
            logger.error(LOG("REC.005.ERROR", max_retries=MAX_RETRIES))


# ── Registry ───────────────────────────────────────────────────
_recorders: dict[str, SegmentRecorder] = {}


def start(transaction_id: str) -> str:
    rec = SegmentRecorder(transaction_id)
    _recorders[transaction_id] = rec
    rec.start()
    return rec.get_raw_dir()


def stop(transaction_id: str) -> Optional[SegmentRecorder]:
    rec = _recorders.pop(transaction_id, None)
    if rec:
        rec.stop()
    return rec


def get(transaction_id: str) -> Optional[SegmentRecorder]:
    return _recorders.get(transaction_id)
