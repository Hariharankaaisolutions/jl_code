"""
cam1/recording/video_writer.py — Detected Video Writer
========================================================
Saves annotated frames to detected video file.
Writes only motion frames with detections.
Max 60 lines. One responsibility: write detected video.
"""

import cv2
import os
from datetime import datetime
from core.config import get, getint
from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("VID")

VIDEO_BASE = get("CAM2_VIDEO_BASE_DIR", "/opt/secure_ai/cam1/video")
FPS        = getint("INFERRED_VIDEO_FPS", 15)
W          = getint("CAM2_FRAME_WIDTH",   640)
H          = getint("CAM2_FRAME_HEIGHT",  640)


class DetectedVideoWriter:
    """Writes annotated detected frames to mp4 file."""

    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id
        self.writer         = None
        self.frame_count    = 0
        self.path           = self._make_path()
        self._open()

    def _make_path(self) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        det_dir  = os.path.join(VIDEO_BASE, date_str, "detected")
        os.makedirs(det_dir, exist_ok=True)
        return os.path.join(det_dir,
            f"{self.transaction_id}_detected.mp4")

    def _open(self) -> None:
        try:
            fourcc     = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer = cv2.VideoWriter(
                self.path, fourcc, FPS, (W, H))
            logger.info(LOG("VID.001.INFO",
                path=self.path, fps=FPS, width=W, height=H))
        except Exception as e:
            logger.error(LOG("VID.002.ERROR",
                path=self.path, error=e))

    def write(self, frame) -> None:
        """Write annotated frame to video."""
        if self.writer and self.writer.isOpened():
            try:
                self.writer.write(frame)
                self.frame_count += 1
            except Exception as e:
                logger.error(LOG("VID.004.ERROR", error=e))

    def close(self) -> None:
        """Close video writer."""
        if self.writer:
            self.writer.release()
            self.writer = None
            logger.info(LOG("VID.003.INFO",
                path=self.path, frames=self.frame_count))
