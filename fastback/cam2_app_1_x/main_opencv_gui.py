# main_opencv_gui.py — OpenCV GUI Helpers
# ======================================

import sys
import os
import cv2
from smart_logger import get_logger

logger = get_logger(__name__)


def gui_available() -> bool:
    """
    Check if OpenCV GUI can be used (X11 available on Linux).
    """
    available = not (
        sys.platform.startswith("linux")
        and not os.environ.get("DISPLAY")
    )
    logger.debug("OpenCV GUI available: %s", available)
    return available


def create_window(name: str, width: int, height: int):
    """
    Safely create and resize OpenCV window.
    """
    if not gui_available():
        return

    try:
        cv2.namedWindow(name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(name, width, height)
    except Exception:
        logger.exception("Failed to create OpenCV window: %s", name)


def destroy_all():
    """
    Safely destroy all OpenCV windows.
    """
    if not gui_available():
        return

    try:
        cv2.destroyAllWindows()
    except Exception:
        logger.exception("Failed to destroy OpenCV windows")
