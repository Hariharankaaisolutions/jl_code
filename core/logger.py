"""
core/logger.py — Unified Logger
=================================
Creates consistent loggers for all modules.
Reads format/level from logging.properties.
Max 80 lines. One responsibility: create and configure loggers.
"""

import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

# ── Load logging config ────────────────────────────────────────
def _load_log_cfg() -> dict:
    cfg = {}
    path = Path("/opt/secure_ai/config/logging.properties")
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


_cfg      = _load_log_cfg()

# Disable root logger to prevent duplicate output
logging.getLogger().handlers.clear()
logging.getLogger().setLevel(logging.WARNING)
_loggers: dict[str, logging.Logger] = {}

LOG_DIR     = _cfg.get("LOG_DIR",    "/var/log/smartcounter")
LOG_PREFIX  = _cfg.get("LOG_PREFIX", "jlcam")
LOG_LEVEL   = _cfg.get("LOG_LEVEL",  "INFO")
LOG_FORMAT  = _cfg.get("LOG_FORMAT",
    "%(asctime)s | %(levelname)-8s | [%(name)-16s] | %(message)s")
LOG_DATE    = _cfg.get("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S")
LOG_MAX_MB  = int(_cfg.get("LOG_MAX_MB",    "50"))
LOG_BACKUPS = int(_cfg.get("LOG_BACKUP_COUNT", "10"))
LOG_CONSOLE = _cfg.get("LOG_CONSOLE", "true").lower() == "true"


def _get_log_path() -> str:
    date_str = datetime.now().strftime("%Y-%m-%d")
    date_dir = os.path.join(LOG_DIR, date_str)
    os.makedirs(date_dir, exist_ok=True)
    return os.path.join(date_dir, f"{LOG_PREFIX}.log")


def _get_level(name: str) -> int:
    key = f"LOG_LEVEL_{name.upper()}"
    level_str = _cfg.get(key, LOG_LEVEL)
    return getattr(logging, level_str.upper(), logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """
    Get or create a named logger.
    Usage: logger = get_logger("CAM1")
    """
    if name in _loggers:
        return _loggers[name]

    logger    = logging.getLogger(name)
    level     = _get_level(name)
    logger.setLevel(level)
    # Clear existing handlers to prevent duplicates on restart
    logger.handlers.clear()
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE)

    # Rotating file handler
    fh = logging.handlers.RotatingFileHandler(
        _get_log_path(),
        maxBytes=LOG_MAX_MB * 1024 * 1024,
        backupCount=LOG_BACKUPS,
        encoding="utf-8",
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler
    if LOG_CONSOLE:
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    logger.propagate = False
    _loggers[name]   = logger
    return logger
