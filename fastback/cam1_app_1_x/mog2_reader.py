# mog2_reader.py — MOG2 Motion Detection Reader (Thread 1)
# =========================================================
# Reads raw_video.mp4 as it is being written (follow mode)
# Runs MOG2 background subtraction on every frame
# Motion detected → saves frame as JPEG to mog2_buffer/
# No motion → discards frame
#
# Runs as a background thread — completely independent of YOLOX
# Raw video writing is never interrupted
# CPU spike → MOG2 still runs, buffer keeps filling
# =========================================================

import os
import cv2
import time
import threading
import numpy as np
from datetime import datetime
from typing import Optional

from jl_logger import get_logger
from daily_counts_db import upsert_mog2_log

logger = get_logger("MOG2")

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
MOG2_ENABLED        = _props.get("MOG2_ENABLED",        "true").lower() == "true"
MOG2_THRESHOLD      = int(_props.get("MOG2_THRESHOLD",  "500"))
MOG2_HISTORY        = int(_props.get("MOG2_HISTORY",    "500"))
MOG2_VAR_THRESHOLD  = int(_props.get("MOG2_VAR_THRESHOLD", "16"))
BUFFER_DIR          = _props.get("MOG2_BUFFER_DIR",
    "/opt/secure_ai/fastback/cam1_app_1_x/detection_videos/mog2_buffer")
BUFFER_FORMAT       = _props.get("MOG2_BUFFER_FORMAT",  "jpg")
BUFFER_QUALITY      = int(_props.get("MOG2_BUFFER_QUALITY", "85"))
FRAME_WIDTH         = int(_props.get("FRAME_WIDTH",     "640"))
FRAME_HEIGHT        = int(_props.get("FRAME_HEIGHT",    "480"))

# How long to wait for new frames before giving up (seconds)
_MAX_WAIT_SECS      = 30
# How often to log stats
_LOG_EVERY_N_FRAMES = 200


# ─────────────────────────────────────────────────
# MOG2Reader class
# ─────────────────────────────────────────────────
class MOG2Reader:
    """
    Reads raw video file as it grows, applies MOG2, saves motion frames to buffer.

    Usage:
        reader = MOG2Reader(
            raw_video_path="/path/to/tx_id.mp4",
            session_id="...",
            transaction_id="...",
            cam="cam_1"
        )
        reader.start()
        # ... later ...
        reader.stop()
        stats = reader.get_stats()
    """

    def __init__(
        self,
        raw_video_path: str,
        session_id:     str,
        transaction_id: str,
        cam:            str = "cam_1",
        rtsp_url:       str = "rtsp://127.0.0.1:8554/live/cam_1",
    ):
        self.raw_video_path = raw_video_path
        self.session_id     = session_id
        self.transaction_id = transaction_id
        self.cam            = cam
        self.rtsp_url       = rtsp_url

        # MOG2 background subtractor
        self.mog2 = cv2.createBackgroundSubtractorMOG2(
            history=MOG2_HISTORY,
            varThreshold=MOG2_VAR_THRESHOLD,
            detectShadows=False,
        )

        # Buffer directory for this session
        today          = datetime.now().strftime("%Y-%m-%d")
        self.buffer_dir = os.path.join(BUFFER_DIR, today, transaction_id)
        os.makedirs(self.buffer_dir, exist_ok=True)

        # Stats
        self.total_frames   = 0
        self.motion_frames  = 0
        self.skipped_frames = 0
        self.frame_index    = 0

        # Control
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started_at: Optional[datetime] = None

        logger.info(
            f"MOG2Reader created → "
            f"session={session_id[:8]} "
            f"tx={transaction_id[:8]} "
            f"cam={cam} "
            f"buffer={self.buffer_dir} "
            f"threshold={MOG2_THRESHOLD} "
            f"history={MOG2_HISTORY}"
        )

    # ─────────────────────────────────────────────
    # Start / Stop
    # ─────────────────────────────────────────────
    def start(self):
        """Start MOG2 reader thread."""
        if self._thread and self._thread.is_alive():
            logger.warning(f"MOG2Reader already running for tx={self.transaction_id[:8]}")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"mog2_{self.transaction_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        self._started_at = datetime.now()
        logger.info(
            f"MOG2Reader thread started → "
            f"tx={self.transaction_id[:8]} "
            f"file={self.raw_video_path}"
        )

    def stop(self):
        """Signal MOG2 reader to stop after current frame."""
        logger.info(f"MOG2Reader stop requested → tx={self.transaction_id[:8]}")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning(
                    f"MOG2Reader thread did not stop cleanly "
                    f"tx={self.transaction_id[:8]}"
                )
        self._flush_stats()
        logger.info(
            f"MOG2Reader stopped → "
            f"tx={self.transaction_id[:8]} "
            f"total={self.total_frames} "
            f"motion={self.motion_frames} "
            f"skipped={self.skipped_frames}"
        )

    def get_stats(self) -> dict:
        """Return current processing stats."""
        elapsed = 0.0
        if self._started_at:
            elapsed = (datetime.now() - self._started_at).total_seconds()
        fps = self.total_frames / elapsed if elapsed > 0 else 0
        motion_pct = (
            (self.motion_frames / self.total_frames * 100)
            if self.total_frames > 0 else 0
        )
        return {
            "total_frames":   self.total_frames,
            "motion_frames":  self.motion_frames,
            "skipped_frames": self.skipped_frames,
            "elapsed_secs":   round(elapsed, 1),
            "fps":            round(fps, 2),
            "motion_pct":     round(motion_pct, 1),
            "buffer_dir":     self.buffer_dir,
        }

    # ─────────────────────────────────────────────
    # Internal run loop
    # ─────────────────────────────────────────────
    def _run(self):
        """Main MOG2 processing loop — runs in background thread."""
        logger.info(
            f"MOG2 loop starting → "
            f"connecting to RTSP: {self.rtsp_url}"
        )

        # Wait for RTSP stream to be available
        cap = None
        wait_start = time.time()
        while True:
            if self._stop_event.is_set():
                logger.info("MOG2 stopped while waiting for RTSP")
                return
            if time.time() - wait_start > _MAX_WAIT_SECS:
                logger.error(
                    f"MOG2 timed out waiting for RTSP: {self.rtsp_url}"
                )
                return
            test = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            if test.isOpened():
                ret, _ = test.read()
                test.release()
                if ret:
                    break
            else:
                test.release()
            time.sleep(1.0)

        logger.info(f"MOG2 RTSP stream ready: {self.rtsp_url}")

        cap = None
        no_frame_count = 0
        max_no_frame   = 150  # ~10s at 15fps before giving up

        try:
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)

            if not cap.isOpened():
                logger.error(
                    f"MOG2 could not open RTSP: {self.rtsp_url}"
                )
                return

            logger.info(
                f"MOG2 VideoCapture opened → "
                f"rtsp={self.rtsp_url}"
            )

            while not self._stop_event.is_set():
                ret, frame = cap.read()

                if not ret:
                    no_frame_count += 1
                    if no_frame_count >= max_no_frame:
                        logger.info(
                            f"MOG2 no new frames for {max_no_frame} attempts — "
                            f"raw video likely finished"
                        )
                        break
                    time.sleep(0.067)  # ~15fps wait
                    continue

                no_frame_count = 0
                self.total_frames += 1
                self.frame_index  += 1

                # Resize for MOG2 (faster on smaller frame)
                try:
                    small = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
                    gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                except Exception as e:
                    logger.warning(f"MOG2 frame resize failed: {e}")
                    continue

                # Apply MOG2
                try:
                    fg_mask     = self.mog2.apply(gray)
                    motion_area = cv2.countNonZero(fg_mask)
                except Exception as e:
                    logger.warning(f"MOG2 apply failed frame={self.frame_index}: {e}")
                    continue

                if motion_area < MOG2_THRESHOLD:
                    self.skipped_frames += 1
                    continue

                # Motion detected — save to buffer
                self.motion_frames += 1
                ts     = datetime.now().strftime("%H%M%S_%f")[:12]
                fname  = f"{self.frame_index:08d}_{ts}.{BUFFER_FORMAT}"
                fpath  = os.path.join(self.buffer_dir, fname)

                try:
                    encode_params = []
                    if BUFFER_FORMAT == "jpg":
                        encode_params = [cv2.IMWRITE_JPEG_QUALITY, BUFFER_QUALITY]
                    cv2.imwrite(fpath, small, encode_params)
                except Exception as e:
                    logger.error(
                        f"MOG2 buffer write failed "
                        f"frame={self.frame_index} "
                        f"path={fpath}: {e}",
                        exc_info=True
                    )
                    continue

                # Log stats every N frames
                if self.total_frames % _LOG_EVERY_N_FRAMES == 0:
                    stats = self.get_stats()
                    logger.info(
                        f"MOG2 stats → "
                        f"total={stats['total_frames']} "
                        f"motion={stats['motion_frames']} ({stats['motion_pct']}%) "
                        f"skipped={stats['skipped_frames']} "
                        f"fps={stats['fps']} "
                        f"buffer_pending="
                        f"{self._count_buffer_files()}"
                    )
                    # Update DB stats
                    self._flush_stats()

        except Exception as e:
            logger.error(
                f"MOG2 reader loop crashed: {e}",
                exc_info=True
            )
        finally:
            if cap:
                try:
                    cap.release()
                except Exception:
                    pass
            self._flush_stats()
            logger.info(
                f"MOG2 reader loop ended → "
                f"total={self.total_frames} "
                f"motion={self.motion_frames} "
                f"skipped={self.skipped_frames}"
            )

    # ─────────────────────────────────────────────
    # Buffer file count
    # ─────────────────────────────────────────────
    def _count_buffer_files(self) -> int:
        try:
            return sum(
                1 for f in os.listdir(self.buffer_dir)
                if f.endswith(f".{BUFFER_FORMAT}")
            )
        except Exception:
            return -1

    # ─────────────────────────────────────────────
    # Flush stats to DB
    # ─────────────────────────────────────────────
    def _flush_stats(self):
        try:
            upsert_mog2_log(
                session_id=self.session_id,
                transaction_id=self.transaction_id,
                cam=self.cam,
                total_frames=self.total_frames,
                motion_frames=self.motion_frames,
                skipped_frames=self.skipped_frames,
            )
        except Exception as e:
            logger.error(f"MOG2 flush stats failed: {e}", exc_info=True)


# ─────────────────────────────────────────────────
# Active readers registry
# ─────────────────────────────────────────────────
_readers: dict[str, MOG2Reader] = {}
_lock = threading.Lock()

def start_mog2_reader(
    raw_video_path: str,
    session_id:     str,
    transaction_id: str,
    cam:            str = "cam_1",
) -> Optional[MOG2Reader]:
    """
    Create and start a MOG2 reader for a session.
    Returns the reader instance.
    """
    if not MOG2_ENABLED:
        logger.info("MOG2_ENABLED=false — skipping MOG2 reader")
        return None

    try:
        reader = MOG2Reader(
            raw_video_path=raw_video_path,
            session_id=session_id,
            transaction_id=transaction_id,
            cam=cam,
        )
        reader.start()
        with _lock:
            _readers[transaction_id] = reader
        logger.info(f"MOG2 reader registered → tx={transaction_id[:8]}")
        return reader
    except Exception as e:
        logger.error(f"start_mog2_reader failed: {e}", exc_info=True)
        return None

def stop_mog2_reader(transaction_id: str) -> dict:
    """Stop and remove a MOG2 reader. Returns final stats."""
    with _lock:
        reader = _readers.pop(transaction_id, None)
    if reader:
        reader.stop()
        stats = reader.get_stats()
        logger.info(f"MOG2 reader removed → tx={transaction_id[:8]} stats={stats}")
        return stats
    logger.warning(f"stop_mog2_reader: no reader found for tx={transaction_id[:8]}")
    return {}

def get_mog2_buffer_dir(transaction_id: str) -> Optional[str]:
    """Get buffer directory for a transaction. Used by YOLOX processor."""
    with _lock:
        reader = _readers.get(transaction_id)
    if reader:
        return reader.buffer_dir
    # Reconstruct path if reader not in memory
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(BUFFER_DIR, today, transaction_id)

