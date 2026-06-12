# main_config.py — Centralized Config Wrapper
# ===========================================

# REPLACE WITH:
from config_loader import (
    EXP_FILE,         # ← ADD
    MODEL_PATH,
    FRAME_WIDTH,
    FRAME_HEIGHT,
    CROSS_LINE_X,
    ENTRY_LINE_X,
    CONF_THRES,
    IOU_THRES,        # ← ADD (was IOU_THRESHOLD before, now consistent)
    CROSS_DIRECTION,
    GHOST_MATCH_DIST_PX,
    GHOST_MAX_AGE_FRAMES,
    RTMP_BASE_URL,
    VIDEO_SAVE_DIR,
    DAYS_TO_KEEP,
    FASTAPI_TITLE,
    ALLOWED_ORIGINS,
    HOST,
    PORT,
    DETECTION_MODE,
    RAW_VIDEO_GRAYSCALE,
    DETECTED_VIDEO_GRAYSCALE,
    DETECTED_FRAME_GRAYSCALE,
)

# UPDATE __all__ — remove YOLOV5_PATH, add EXP_FILE and IOU_THRES:
__all__ = [
    "EXP_FILE",        # ← CHANGED
    "MODEL_PATH",
    "FRAME_WIDTH",
    "FRAME_HEIGHT",
    "CROSS_LINE_X",
    "ENTRY_LINE_X",
    "CONF_THRES",
    "IOU_THRES",       # ← CHANGED
    "CROSS_DIRECTION",
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