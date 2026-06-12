# main_video_utils.py — Video Helper Utilities
# ============================================

import cv2
from typing import Tuple, Optional
from smart_logger import get_logger

logger = get_logger(__name__)


# -------------------------------------------------
# Safe Resize
# -------------------------------------------------
def safe_resize(frame, width: int, height: int):
    """
    Safely resize a video frame.
    If resize fails, original frame is returned.
    """
    if frame is None:
        logger.warning("safe_resize called with None frame")
        return frame

    try:
        return cv2.resize(frame, (width, height))
    except Exception:
        logger.exception(
            "Frame resize failed (width=%s height=%s)", width, height
        )
        return frame


# -------------------------------------------------
# Draw Text Label
# -------------------------------------------------
def draw_label(
    frame,
    text: str,
    x: int,
    y: int,
    scale: float = 0.5,
    color: Tuple[int, int, int] = (255, 255, 255),
    thickness: int = 1,
):
    """
    Draw a text label on a frame.
    """
    if frame is None:
        logger.warning("draw_label called with None frame")
        return

    try:
        cv2.putText(
            frame,
            text,
            (int(x), int(y)),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color,
            thickness,
            cv2.LINE_AA,
        )
    except Exception:
        logger.exception(
            "Failed to draw label: text=%s position=(%s,%s)",
            text, x, y
        )


# -------------------------------------------------
# Draw Bounding Box
# -------------------------------------------------
def draw_box(
    frame,
    x1,
    y1,
    x2,
    y2,
    color: Tuple[int, int, int] = (0, 255, 0),
    thickness: int = 2,
):
    """
    Draw a bounding box on a frame.
    """
    if frame is None:
        logger.warning("draw_box called with None frame")
        return

    try:
        cv2.rectangle(
            frame,
            (int(x1), int(y1)),
            (int(x2), int(y2)),
            color,
            thickness,
        )
    except Exception:
        logger.exception(
            "Failed to draw bounding box: (%s,%s,%s,%s)",
            x1, y1, x2, y2
        )
