# config_loader.py — Minimal-change loader for app.properties + .env
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env for secrets (SMTP, DB password etc.)
_env_path = BASE_DIR / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

# Load app.properties
PROPERTIES_FILE = BASE_DIR / "app.properties"
PROPS = {}
if PROPERTIES_FILE.exists():
    with open(PROPERTIES_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                PROPS[k.strip()] = v.strip()


# ------------------------- Generic Getters ------------------------- #
def get(key, default=None):
    # env overrides properties
    return os.getenv(key, PROPS.get(key, default))


def getint(key, default=0):
    val = get(key, None)
    try:
        return int(val)
    except Exception:
        return int(default)


def getfloat(key, default=0.0):
    val = get(key, None)
    try:
        return float(val)
    except Exception:
        return float(default)


def getbool(key, default=False):
    val = get(key, None)
    if val is None:
        return bool(default)
    if isinstance(val, bool):
        return val
    v = str(val).strip().lower()
    return v in ("1", "true", "yes", "on")


def getlist(key, sep=","):
    val = get(key, None)
    if val is None:
        return []
    return [x.strip() for x in str(val).split(sep) if x.strip()]


def getmap(key, item_sep=",", kv_sep=":"):
    val = get(key, None)
    if not val:
        return {}
    out = {}
    for item in str(val).split(item_sep):
        if kv_sep in item:
            k, v = item.split(kv_sep, 1)
            k = k.strip()
            v = v.strip()
            try:
                out[k] = int(v)
            except Exception:
                out[k] = v
    return out


# ------------------------- YOLO / Detection ------------------------- #
EXP_FILE  = get("EXP_FILE",   "yolox_s.py")
IOU_THRES = getfloat("IOU_THRES", 0.45)
MODEL_PATH              = get("MODEL_PATH",               "yolo_instance_box.pt")
BOX_MODEL_PATH          = MODEL_PATH
BALE_MODEL_PATH         = MODEL_PATH
CONF_THRES              = getfloat("CONF_THRES",           0.4)
IOU_THRESHOLD           = getfloat("IOU_THRESHOLD",        0.45)
FRAME_WIDTH             = getint("FRAME_WIDTH",            640)
FRAME_HEIGHT            = getint("FRAME_HEIGHT",           480)
CROSS_LINE_X            = getint("CROSS_LINE_X",           300)
ENTRY_LINE_X            = getint("ENTRY_LINE_X",           600)
GHOST_MATCH_DIST_PX     = getint("GHOST_MATCH_DIST_PX",    80)
GHOST_MAX_AGE_FRAMES    = getint("GHOST_MAX_AGE_FRAMES",   45)
ALLOWED_CLASSES         = getlist("ALLOWED_CLASSES") or ["box", "bale", "trolley"]
MAX_DETECTIONS_PER_FRAME= getint("MAX_DETECTIONS_PER_FRAME", 50)

# Controls which direction an object must cross the line to be counted.
# "left"  → object moves right-to-left  (old_cx > CROSS_LINE_X >= cx)
# "right" → object moves left-to-right  (old_cx < CROSS_LINE_X <= cx)
CROSS_DIRECTION         = get("CROSS_DIRECTION", "left").strip().lower()

# ------------------------- Detection Mode ------------------------- #
DETECTION_MODE           = get("DETECTION_MODE", "rgb").strip().lower()
RAW_VIDEO_GRAYSCALE      = getbool("RAW_VIDEO_GRAYSCALE",      False)
DETECTED_VIDEO_GRAYSCALE = getbool("DETECTED_VIDEO_GRAYSCALE", False)
DETECTED_FRAME_GRAYSCALE = getbool("DETECTED_FRAME_GRAYSCALE", False)

# ------------------------- Tracker ------------------------- #
TRACKER_MAX_DISTANCE    = getint("TRACKER_MAX_DISTANCE",   50)
TRACKER_MAX_MISSES      = getint("TRACKER_MAX_MISSES",     10)
TRACKER_MIN_HITS        = getint("TRACKER_MIN_HITS",        2)

# ------------------------- Object mappings ------------------------- #
# BOX_CLASSES  : read from app.properties e.g. box:1
# BALE_CLASSES : read from app.properties e.g. bale:1,fbale:1,sbale:2,tbale_a:2,tbale_b:2
#
# These dicts are used in TWO places:
#   1. session.py        — decides HOW MUCH to increment box/bale counter
#   2. main_detection.py — CLASS_WEIGHTS uses the keys as the allowed label gate
BOX_CLASSES     = getmap("BOX_CLASSES")
BALE_CLASSES    = getmap("BALE_CLASSES")
DEFAULT_COUNTS  = getmap("DEFAULT_COUNTS")

# ------------------------- Behavior ------------------------- #
ENABLE_GUI                  = getbool("ENABLE_GUI",                  False)
ASYNC_SLEEP_TIME            = getfloat("ASYNC_SLEEP_TIME",           0.0)
SAVE_FIRST_FRAME            = getbool("SAVE_FIRST_FRAME",            True)
SAVE_COUNTED_FRAME          = getbool("SAVE_COUNTED_FRAME",          True)
END_SESSION_ON_VIDEO_FREEZE = getbool("END_SESSION_ON_VIDEO_FREEZE", True)
MAX_FREEZE_FRAMES           = getint("MAX_FREEZE_FRAMES",            30)

# ------------------------- Video & Paths ------------------------- #
VIDEO_SAVE_DIR          = get("VIDEO_SAVE_DIR",          str(BASE_DIR / "detection_videos"))
FIRST_FRAME_SAVE_DIR    = get("FIRST_FRAME_SAVE_DIR",    str(BASE_DIR / "first_frames"))
COUNTED_FRAME_SAVE_DIR  = get("COUNTED_FRAME_SAVE_DIR",  str(BASE_DIR / "counted_frames"))
DETECTED_FRAMES_DIR     = get("DETECTED_FRAMES_DIR",     str(BASE_DIR / "detected_frames"))
DAYS_TO_KEEP            = getint("DAYS_TO_KEEP",         10)

VIDEO_FRAME_WIDTH       = getint("VIDEO_FRAME_WIDTH",    640)
VIDEO_FRAME_HEIGHT      = getint("VIDEO_FRAME_HEIGHT",   480)
VIDEO_FPS               = getint("VIDEO_FPS",            20)

# ------------------------- RTMP ------------------------- #
RTMP_BASE_URL   = get("RTMP_BASE_URL",  "rtmp://localhost/live/")
RTMP_USE_AUTH   = getbool("RTMP_USE_AUTH", False)
RTMP_USERNAME   = get("RTMP_USERNAME",  "")
RTMP_PASSWORD   = get("RTMP_PASSWORD",  "")

# ------------------------- FastAPI ------------------------- #
FASTAPI_TITLE   = get("FASTAPI_TITLE",  "YOLOv5 Detection Backend")
ENABLE_DOCS     = getbool("ENABLE_DOCS", True)
ALLOWED_ORIGINS = getlist("ALLOWED_ORIGINS") or ["*"]
HOST            = get("HOST",           "0.0.0.0")
PORT            = getint("PORT",        8000)

# ------------------------- Logging (legacy) ------------------------- #
LOG_DIR         = get("LOG_DIR",        "/opt/vchanel/logs/")
LOG_FILE_NAME   = get("LOG_FILE_NAME",  "backend.log")
LOG_LEVEL       = get("LOG_LEVEL",      "INFO")

# ------------------------- Database ------------------------- #
DB_NAME         = get("DB_NAME",        "jlmill")
DB_USER         = get("DB_USER",        None)
DB_PASSWORD     = get("DB_PASSWORD",    None)
DB_HOST         = get("DB_HOST",        "localhost")
DB_PORT         = getint("DB_PORT",     5432)

# ------------------------- MQTT ------------------------- #
MQTT_ENABLED        = getbool("MQTT_ENABLED",       True)
MQTT_HOST           = get("MQTT_HOST",              "localhost")
MQTT_PORT           = getint("MQTT_PORT",           1883)
MQTT_TOPIC_COUNTS   = get("MQTT_TOPIC_COUNTS",      "jl/counts")
MQTT_TOPIC_BASE     = get("MQTT_TOPIC_BASE",        "jlmill/sessions/")
MQTT_USERNAME       = get("MQTT_USERNAME",          "")
MQTT_PASSWORD       = get("MQTT_PASSWORD",          "")

# ------------------------- Email (from .env) ------------------------- #
SMTP_USERNAME   = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD")
TO_EMAIL        = os.getenv("TO_EMAIL")

# ------------------------- GC ------------------------- #
ENABLE_GC_CLEANUP = getbool("ENABLE_GC_CLEANUP", True)

# ------------------------- Auto-Stop Scheduler ------------------------- #
AUTO_STOP_ENABLED   = getbool("AUTO_STOP_ENABLED", True)
AUTO_STOP_TIME      = get("AUTO_STOP_TIME",        "19:55")
RAW_VIDEO_AUTO_STOP_TIME=get("RAW_VIDEO_AUTO_STOP_TIME",        "19:55")

# ------------------------- Reinforcement Learning ------------------------- #
RL_SAVE_DIR        = get("RL_SAVE_DIR",           "/opt/secure_ai/reinforcement_learning/cam1")
RL_CONF_THRESHOLD  = getfloat("RL_CONF_THRESHOLD", 0.9)
RL_LINE_PROXIMITY_PX = getint("RL_LINE_PROXIMITY_PX", 50)