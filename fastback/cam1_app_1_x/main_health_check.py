# main_health_check.py — System Health Monitoring
# ===============================================

from smart_logger import get_logger
logger = get_logger(__name__)

import time
import shutil
import psutil

from mqtt_push import mqtt_push_error
from message_loader import Messages
from session import session_manager

from main_config import VIDEO_SAVE_DIR


# -------------------------------------------------
# MEMORY CHECK
# -------------------------------------------------
def check_memory(session_id: str, transaction_id: str, threshold: int = 90):
    """
    Check system memory usage.
    Sends MQTT alert if threshold exceeded.
    """
    try:
        mem_percent = psutil.virtual_memory().percent

        if mem_percent > threshold:
            logger.warning(
                Messages.get(
                    "SYSTEM.MEMORY.001.WARN",
                    percent=mem_percent,
                )
            )
            mqtt_push_error(
                session_id=session_id,
                transaction_id=transaction_id,
                error_code="MEMORY_HIGH",
                message=f"Memory usage {mem_percent}%",
                severity="critical",
            )
            return True

        return False

    except Exception:
        logger.exception(Messages.get("SYSTEM.MEMORY.002.ERROR"))
        return False


# -------------------------------------------------
# DISK SPACE CHECK
# -------------------------------------------------
def check_disk_space(
    session_id: str,
    transaction_id: str,
    min_bytes: int = 1_000_000_000
):
    """
    Check disk free space.
    Sends MQTT alert if space is below min_bytes.
    """
    try:
        try:
            _, _, free = shutil.disk_usage(VIDEO_SAVE_DIR)
        except Exception:
            # fallback to root if VIDEO_SAVE_DIR fails
            _, _, free = shutil.disk_usage("/")

        free_mb = free // (1024 * 1024)

        if free < min_bytes:
            logger.warning(
                Messages.get(
                    "SYSTEM.DISK.001.WARN",
                    free_mb=free_mb,
                )
            )
            mqtt_push_error(
                session_id=session_id,
                transaction_id=transaction_id,
                error_code="DISK_SPACE_LOW",
                message=f"Only {free_mb} MB free on server",
                severity="critical",
            )
            return True

        return False

    except Exception:
        logger.exception(Messages.get("SYSTEM.DISK.002.ERROR"))
        return False


# -------------------------------------------------
# FPS CHECK
# -------------------------------------------------
def check_fps(
    session_id: str,
    transaction_id: str,
    frame_index: int,
    loop_start_time: float,
    threshold: float = 5.0,
):
    """
    Check approximate FPS.
    Sends MQTT alert if FPS drops below threshold.
    """
    try:
        elapsed = time.time() - loop_start_time

        if elapsed <= 0:
            return False, None

        fps = frame_index / elapsed

        if fps < threshold:
            logger.warning(
                Messages.get(
                    "SYSTEM.FPS.001.WARN",
                    fps=fps,
                )
            )
            mqtt_push_error(
                session_id=session_id,
                transaction_id=transaction_id,
                error_code="FPS_DROP",
                message=f"Detection FPS dropped to {fps:.2f}",
                severity="medium",
            )
            return True, fps

        return False, fps

    except Exception:
        logger.exception(Messages.get("SYSTEM.FPS.002.ERROR"))
        return False, None
