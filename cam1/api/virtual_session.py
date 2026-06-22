"""
cam1/api/virtual_session.py — Virtual Mobile Session
======================================================
Mobile users get a virtual session — illusion of start/stop.
Real detection continues uninterrupted in background.
Counts shown = real counts - snapshot at mobile start time.
Max 80 lines. One responsibility: virtual session management.
"""

import uuid
import threading
from datetime import datetime
from typing import Optional

from core.config import get
from core.logger import get_logger
from core.log_codes import get as LOG
from core.db_transaction import insert_transaction, end_transaction
from core.mqtt import publish_counts

logger = get_logger("SESS")

# ── Active virtual sessions per user ───────────────────────────
_virtual: dict[str, dict] = {}
_lock = threading.Lock()

DEFAULT = {"box": 0, "bale": 0, "trolley": 0, "bag": 0}


def has_active(user_id: str) -> bool:
    """Check if user already has an active virtual session."""
    s = _virtual.get(user_id)
    return bool(s and s.get("active"))


def start(
    user_id:        str,
    transaction_id: str,
    session_id:     str,
    name:           str,
    role:           str,
    device_id:      str,
    vehicle_number: str,
    cam:            str,
    real_counts:    dict,
) -> bool:
    """
    Start virtual session for mobile user.
    Snapshots real counts at start time.
    """
    with _lock:
        if has_active(user_id):
            logger.warning(LOG("SESS.017.WARN", user_id=user_id))
            return False

        start_time = datetime.now().strftime("%H:%M:%S")
        _virtual[user_id] = {
            "transaction_id": transaction_id,
            "session_id":     session_id,
            "name":           name,
            "role":           role,
            "device_id":      device_id,
            "vehicle_number": vehicle_number,
            "cam":            cam,
            "start_time":     start_time,
            "active":         True,
            "snapshot":       real_counts.copy(),
        }

        insert_transaction(
            transaction_id=transaction_id,
            session_id=session_id,
            name=name, role=role,
            user_id=user_id,
            device_unique_id=device_id,
            cam=cam,
            vehicle_number=vehicle_number,
            start_time=start_time,
        )
        logger.info(LOG("SESS.013.INFO",
            user_id=user_id, tx_id=transaction_id[:8]))
        logger.info(LOG("SESS.014.INFO",
            user_id=user_id, snapshot=real_counts))
        return True


def publish_virtual_counts(real_counts: dict) -> None:
    """Publish offset counts for all active virtual sessions via MQTT."""
    for user_id, s in _virtual.items():
        if not s.get("active"):
            continue
        offset = {
            k: max(0, real_counts.get(k, 0) - s["snapshot"].get(k, 0))
            for k in DEFAULT
        }
        publish_counts(
            session_id=s["session_id"],
            transaction_id=s["transaction_id"],
            counts=offset
        )


def get_counts(user_id: str, real_counts: dict) -> dict:
    """Return offset counts (real - snapshot at start)."""
    s = _virtual.get(user_id)
    if not s:
        return DEFAULT.copy()
    snap = s.get("snapshot", DEFAULT)
    return {
        k: max(0, real_counts.get(k, 0) - snap.get(k, 0))
        for k in DEFAULT
    }


def stop(user_id: str, real_counts: dict) -> Optional[dict]:
    """Stop virtual session. Save final offset counts to DB."""
    with _lock:
        s = _virtual.get(user_id)
        if not s or not s.get("active"):
            logger.warning(LOG("SESS.009.WARN",
                session_id=user_id))
            return None

        s["active"]   = False
        end_time      = datetime.now().strftime("%H:%M:%S")
        offset_counts = get_counts(user_id, real_counts)

        end_transaction(
            transaction_id=s["transaction_id"],
            end_time=end_time,
            box_count=offset_counts.get("box", 0),
            bale_count=offset_counts.get("bale", 0),
            bag_count=offset_counts.get("bag", 0),
            trolley_count=offset_counts.get("trolley", 0),
        )
        logger.info(LOG("SESS.015.INFO",
            user_id=user_id, counts=offset_counts))
        return {**s, "end_time": end_time, "counts": offset_counts}
