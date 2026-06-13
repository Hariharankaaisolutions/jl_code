# jl_logger.py — Unified Logger for JL-CAM System
# =================================================
# Single log file for ALL components:
#   CAM1 API, inference, MOG2, YOLOX, health, MQTT,
#   auto-start, boot report, system metrics, FFmpeg events
#
# Log file: /var/log/smartcounter/jlcam_YYYY-MM-DD.log
# Format:   YYYY-MM-DD HH:MM:SS.mmm | LEVEL    | [COMPONENT] | message
# Rotation: 50MB per file, 10 backups, zip after 2 days, delete after 14 days
# Thread-safe: yes (RotatingFileHandler + QueueHandler)
# =================================================

import logging
import logging.handlers
import os
import gzip
import shutil
import queue
import threading
from datetime import datetime, timedelta
from pathlib import Path

# ─────────────────────────────────────────────────
# Load config from app.properties
# ─────────────────────────────────────────────────
_PROPS_FILE = os.path.join(os.path.dirname(__file__), "app.properties")

def _load_props() -> dict:
    props = {}
    try:
        with open(_PROPS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
    except Exception:
        pass
    return props

_props = _load_props()

# ─────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────
LOG_DIR             = _props.get("UNIFIED_LOG_DIR",           "/var/log/smartcounter")
LOG_PREFIX          = _props.get("UNIFIED_LOG_PREFIX",        "jlcam")
LOG_MAX_MB          = int(_props.get("UNIFIED_LOG_MAX_MB",    "50"))
LOG_BACKUP_COUNT    = int(_props.get("UNIFIED_LOG_BACKUP_COUNT", "10"))
ZIP_AFTER_DAYS      = int(_props.get("UNIFIED_LOG_ZIP_AFTER_DAYS",    "2"))
DELETE_AFTER_DAYS   = int(_props.get("UNIFIED_LOG_DELETE_AFTER_DAYS", "14"))

# Log level from logging.properties
_LOG_PROPS_FILE = os.path.join(os.path.dirname(__file__), "logging.properties")
def _load_log_level() -> int:
    try:
        with open(_LOG_PROPS_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("LOGGING.MODE="):
                    mode = line.split("=", 1)[1].strip().upper()
                    return {"A": logging.DEBUG, "B": logging.INFO, "C": logging.ERROR}.get(mode, logging.INFO)
    except Exception:
        pass
    return logging.INFO

_LOG_LEVEL = _load_log_level()

# ─────────────────────────────────────────────────
# Log file path — one file per day
# ─────────────────────────────────────────────────
def _log_path() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOG_DIR, f"{LOG_PREFIX}_{today}.log")

# ─────────────────────────────────────────────────
# Cleanup old logs — zip after N days, delete after M days
# ─────────────────────────────────────────────────
def _cleanup_old_logs():
    try:
        if not os.path.exists(LOG_DIR):
            return
        now = datetime.now()
        for fname in os.listdir(LOG_DIR):
            if not fname.startswith(LOG_PREFIX):
                continue
            fpath = os.path.join(LOG_DIR, fname)
            if not os.path.isfile(fpath):
                continue
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            age   = (now - mtime).days

            if age >= DELETE_AFTER_DAYS:
                try:
                    os.remove(fpath)
                except Exception:
                    pass
                continue

            if age >= ZIP_AFTER_DAYS and not fname.endswith(".gz"):
                gz_path = fpath + ".gz"
                try:
                    with open(fpath, "rb") as f_in:
                        with gzip.open(gz_path, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.remove(fpath)
                except Exception:
                    pass
    except Exception:
        pass

# ─────────────────────────────────────────────────
# Custom formatter
# ─────────────────────────────────────────────────
class _JLFormatter(logging.Formatter):
    """
    Format: YYYY-MM-DD HH:MM:SS.mmm | LEVEL    | [COMPONENT     ] | message
    Example:
      2026-06-12 10:45:55.234 | INFO     | [INFERENCE     ] | frame=100 fps=15.4 gap=65ms
      2026-06-12 10:46:01.456 | WARNING  | [MEDIAMTX      ] | write queue full (1/3)
      2026-06-12 10:46:20.789 | ERROR    | [AUTOSTART     ] | Session crashed. Restarting in 30s
    """
    LEVEL_WIDTH    = 8
    COMPONENT_WIDTH = 15

    def format(self, record: logging.LogRecord) -> str:
        ts        = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.") + \
                    f"{int(record.msecs):03d}"
        level     = record.levelname.ljust(self.LEVEL_WIDTH)
        component = getattr(record, "component", record.name).upper()
        component = component[:self.COMPONENT_WIDTH].ljust(self.COMPONENT_WIDTH)
        msg       = record.getMessage()

        # Add exception info if present
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            msg = f"{msg}\n{record.exc_text}"

        return f"{ts} | {level} | [{component}] | {msg}"

# ─────────────────────────────────────────────────
# Async queue handler — non-blocking log writes
# ─────────────────────────────────────────────────
_log_queue    = queue.Queue(maxsize=10000)
_queue_handler = logging.handlers.QueueHandler(_log_queue)

# File handler
os.makedirs(LOG_DIR, exist_ok=True)
_file_handler = logging.handlers.RotatingFileHandler(
    _log_path(),
    maxBytes=LOG_MAX_MB * 1024 * 1024,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8"
)
_file_handler.setFormatter(_JLFormatter())
_file_handler.setLevel(_LOG_LEVEL)

# Console handler
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_JLFormatter())
_console_handler.setLevel(_LOG_LEVEL)

# Queue listener — writes to file + console in background thread
_listener = logging.handlers.QueueListener(
    _log_queue,
    _file_handler,
    _console_handler,
    respect_handler_level=True
)
_listener.start()

# Run cleanup once at startup
_cleanup_old_logs()

# ─────────────────────────────────────────────────
# Component logger factory
# ─────────────────────────────────────────────────
_loggers: dict = {}
_lock = threading.Lock()

def get_logger(component: str) -> logging.Logger:
    """
    Get a logger for a component. All loggers write to the same unified file.

    Usage:
        from jl_logger import get_logger
        logger = get_logger("INFERENCE")
        logger.info("frame=100 fps=15.4")
        logger.warning("CPU spike=82% — inference paused")
        logger.error("Session crashed", exc_info=True)

    Components (use these names for consistent log parsing):
        SYSTEM      → boot, shutdown, OS-level events
        MEDIAMTX    → stream publishing, readers, errors
        FFMPEG      → encoder stats, errors, restarts
        API         → HTTP requests, session start/stop
        INFERENCE   → YOLOX frame processing, timing
        MOG2        → motion detection stats
        AUTOSTART   → auto-session management
        HEALTH      → CPU, RAM, disk, GPU metrics
        MQTT        → publish/subscribe events
        DATABASE    → DB queries, errors
        SESSION     → session lifecycle
        RAWVIDEO    → raw video recording
        BUFFER      → MOG2 buffer read/write
        BOOTREPORT  → boot email
        HOUSEKEEP   → cleanup events
        CLOUD       → cloud API events
    """
    with _lock:
        if component in _loggers:
            return _loggers[component]

        logger = logging.getLogger(f"jlcam.{component.lower()}")
        logger.setLevel(_LOG_LEVEL)
        logger.propagate = False

        # Add queue handler only (listener handles actual writing)
        if not logger.handlers:
            h = logging.handlers.QueueHandler(_log_queue)
            h.setLevel(_LOG_LEVEL)
            logger.addHandler(h)

        # Store component name as default extra
        logger = logging.LoggerAdapter(logger, {"component": component})

        _loggers[component] = logger
        return logger

# ─────────────────────────────────────────────────
# Convenience: log separator for session boundaries
# ─────────────────────────────────────────────────
def log_separator(component: str, label: str = ""):
    logger = get_logger(component)
    sep = "=" * 60
    logger.info(f"{sep} {label} {sep}" if label else sep)

# ─────────────────────────────────────────────────
# Shutdown hook — flush all pending log records
# ─────────────────────────────────────────────────
def shutdown():
    """Call at application shutdown to flush all pending logs."""
    try:
        _listener.stop()
    except Exception:
        pass

# ─────────────────────────────────────────────────
# Backward compatibility — drop-in for smart_logger
# ─────────────────────────────────────────────────
def get_smart_logger(module_name: str) -> logging.Logger:
    """Backward compat wrapper for existing smart_logger.get_logger() calls."""
    return get_logger(module_name.upper().replace("_", "").replace("MAIN", "")[:15] or module_name.upper()[:15])

