"""
cam1/detection/mog2.py — GPU MOG2 Filter
==========================================
Background subtraction using CUDA-accelerated MOG2.
Loads exclusion zones from cam1/exclusion_zones.json.
Max 80 lines. One responsibility: motion detection.
"""

import cv2
import json
import numpy as np
from pathlib import Path
from typing import Optional

from core.config import get, getint, getbool
from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("MOG2")

BASE         = Path("/opt/secure_ai")
ZONES_PATH   = BASE / get("CAM1_EXCLUSION_ZONES", "cam1/exclusion_zones.json")
HISTORY      = getint("MOG2_HISTORY",        500)
VAR_THRESH   = getint("MOG2_VAR_THRESHOLD",  16)
MIN_AREA     = getint("MOG2_MOTION_MIN_AREA", 500)
SHADOWS      = getbool("MOG2_DETECT_SHADOWS", True)
SHADOW_THRESH = getint("MOG2_SHADOW_THRESHOLD", 200)


class MOG2Filter:
    """GPU-accelerated background subtractor with exclusion zones."""

    def __init__(self, width: int, height: int):
        self.width   = width
        self.height  = height
        self.stream  = None
        self.mog2    = None
        self.gpu     = False
        self.mask    = None
        self.zones   = []
        self.kernel  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self._init_mog2()
        self._load_zones()

    def _init_mog2(self) -> None:
        try:
            self.stream = cv2.cuda.Stream()
            self.mog2   = cv2.cuda.createBackgroundSubtractorMOG2(
                history=HISTORY,
                varThreshold=VAR_THRESH,
                detectShadows=SHADOWS,
            )
            self.gpu = True
            logger.info(LOG("MOG2.001.INFO",
                mode="GPU", history=HISTORY, threshold=VAR_THRESH))
        except Exception as e:
            logger.warning(LOG("MOG2.002.WARN", error=e))
            self.mog2 = cv2.createBackgroundSubtractorMOG2(
                history=HISTORY,
                varThreshold=VAR_THRESH,
                detectShadows=False,
            )
            self.gpu = False
            logger.info(LOG("MOG2.003.INFO"))

    def _load_zones(self) -> None:
        try:
            if ZONES_PATH.exists():
                with open(ZONES_PATH) as f:
                    self.zones = json.load(f)
                self.mask = np.ones((self.height, self.width), dtype=np.uint8) * 255
                for zone in self.zones:
                    pts = np.array(zone, dtype=np.int32)
                    cv2.fillPoly(self.mask, [pts], 0)
                logger.info(LOG("MOG2.004.INFO", count=len(self.zones)))
                logger.info(LOG("MOG2.007.INFO",
                    pixels=cv2.countNonZero(self.mask)))
            else:
                logger.warning(LOG("MOG2.005.WARN", path=str(ZONES_PATH)))
        except Exception as e:
            logger.error(LOG("MOG2.006.ERROR", error=e))

    def has_motion(self, frame: np.ndarray) -> tuple[bool, np.ndarray]:
        """
        Check if frame has significant motion.
        Returns (has_motion, fg_mask).
        """
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if self.gpu:
                gpu_gray = cv2.cuda_GpuMat()
                gpu_gray.upload(gray)
                gpu_mask = self.mog2.apply(gpu_gray, -1, self.stream)
                fg = gpu_mask.download()
            else:
                fg = self.mog2.apply(gray)

            # Remove shadows
            _, fg = cv2.threshold(fg, SHADOW_THRESH, 255, cv2.THRESH_BINARY)

            # Morphological cleanup
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN,  self.kernel)
            fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self.kernel)

            # Apply exclusion zones
            if self.mask is not None:
                fg = cv2.bitwise_and(fg, self.mask)

            # Check contours
            contours, _ = cv2.findContours(
                fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            significant = [c for c in contours
                          if cv2.contourArea(c) > MIN_AREA]

            return len(significant) > 0, fg

        except Exception as e:
            logger.error(LOG("MOG2.009.ERROR", error=e, frame_num=0))
            return True, np.zeros((self.height, self.width), dtype=np.uint8)

    def draw_zones(self, frame: np.ndarray) -> np.ndarray:
        """Draw exclusion zones on frame."""
        for zone in self.zones:
            pts = np.array(zone, dtype=np.int32)
            cv2.polylines(frame, [pts], True, (0, 0, 255), 1)
        return frame
