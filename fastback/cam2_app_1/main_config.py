# main_config.py — Centralized Config Wrapper
# ===========================================

from config_loader import (
    YOLOV5_PATH,
    MODEL_PATH,
    FRAME_WIDTH,
    FRAME_HEIGHT,
    CROSS_LINE_X,
    ENTRY_LINE_X,
    CONF_THRES,
    GHOST_MATCH_DIST_PX,
    GHOST_MAX_AGE_FRAMES,
    RTMP_BASE_URL,
    VIDEO_SAVE_DIR,
    DAYS_TO_KEEP,
    FASTAPI_TITLE,
    ALLOWED_ORIGINS,
    HOST,
    PORT,
    # Detection mode switches
    DETECTION_MODE,
    RAW_VIDEO_GRAYSCALE,
    DETECTED_VIDEO_GRAYSCALE,
    DETECTED_FRAME_GRAYSCALE,
)

__all__ = [
    "YOLOV5_PATH",
    "MODEL_PATH",
    "FRAME_WIDTH",
    "FRAME_HEIGHT",
    "CROSS_LINE_X",
    "ENTRY_LINE_X",
    "CONF_THRES",
    "GHOST_MATCH_DIST_PX",
    "GHOST_MAX_AGE_FRAMES",
    "RTMP_BASE_URL",
    "VIDEO_SAVE_DIR",
    "DAYS_TO_KEEP",
    "FASTAPI_TITLE",
    "ALLOWED_ORIGINS",
    "HOST",
    "PORT",
    "DETECTION_MODE",
    "RAW_VIDEO_GRAYSCALE",
    "DETECTED_VIDEO_GRAYSCALE",
    "DETECTED_FRAME_GRAYSCALE",
]