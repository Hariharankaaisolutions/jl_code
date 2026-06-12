# main_logging_setup.py — Logging Bootstrap
# =========================================

"""
Central logging bootstrap for the YOLO backend.

Importing this module ensures:
- smart_logger is initialized exactly once
- a shared application-wide logger is available
"""

from smart_logger import get_logger

# Application-wide logger
logger = get_logger("yolo_backend")

# Explicit public API
__all__ = ["logger"]
