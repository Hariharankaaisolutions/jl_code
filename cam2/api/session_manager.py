"""
cam1/api/session_manager.py — Session Manager
===============================================
Manages active detection sessions for cam1.
Tracks session state, counts, and metadata.
Max 80 lines. One responsibility: manage sessions.
"""

import threading
from datetime import datetime
from typing import Optional

from core.config import getmap
from core.logger import get_logger
from core.log_codes import get as LOG
from core.db_transaction import insert_transaction, end_transaction

logger = get_logger("SESS")

DEFAULT_COUNTS = {"box": 0, "bale": 0, "trolley": 0, "bag": 0}


class SessionManager:
    """Manages active detection sessions."""

    def __init__(self):
        self._sessions: dict = {}
        self._lock = threading.Lock()

    def start(
        self,
        session_id: str,
        transaction_id: str,
        name: str,
        role: str,
        user_id: str,
        device_id: str,
        vehicle_number: str,
        cam: str = "cam_1",
    ) -> bool:
        with self._lock:
            if session_id in self._sessions:
                logger.warning(LOG("SESS.003.WARN",
                    session_id=session_id[:8]))
                return False
            start_time = datetime.now().strftime("%H:%M:%S")
            self._sessions[session_id] = {
                "transaction_id": transaction_id,
                "name":           name,
                "role":           role,
                "user_id":        user_id,
                "device_id":      device_id,
                "vehicle_number": vehicle_number,
                "cam":            cam,
                "start_time":     start_time,
                "active":         True,
                "counts":         DEFAULT_COUNTS.copy(),
                "image_path":     None,
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
            logger.info(LOG("SESS.002.INFO",
                session_id=session_id[:8], tx_id=transaction_id[:8]))
            return True

    def stop(self, session_id: str) -> Optional[dict]:
        with self._lock:
            s = self._sessions.get(session_id)
            if not s:
                logger.warning(LOG("SESS.009.WARN",
                    session_id=session_id[:8]))
                return None
            s["active"]   = False
            s["end_time"] = datetime.now().strftime("%H:%M:%S")
            end_transaction(
                transaction_id=s["transaction_id"],
                end_time=s["end_time"],
                box_count=s["counts"].get("box", 0),
                bale_count=s["counts"].get("bale", 0),
                bag_count=s["counts"].get("bag", 0),
                trolley_count=s["counts"].get("trolley", 0),
                image_path=s.get("image_path"),
            )
            logger.info(LOG("SESS.006.INFO",
                session_id=session_id[:8],
                tx_id=s["transaction_id"][:8]))
            return s

    def is_active(self, session_id: str) -> bool:
        s = self._sessions.get(session_id)
        return bool(s and s.get("active"))

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def any_active(self) -> bool:
        return any(s.get("active") for s in self._sessions.values())

    def get_active_sessions(self) -> list:
        return [
            {"session_id": sid, "transaction_id": s["transaction_id"]}
            for sid, s in self._sessions.items()
            if s.get("active")
        ]

    def update_counts(self, session_id: str, counts: dict) -> None:
        with self._lock:
            s = self._sessions.get(session_id)
            if s:
                s["counts"].update(counts)
                logger.info(LOG("SESS.010.INFO",
                    session_id=session_id[:8], counts=counts))

    def update_image_path(self, session_id: str, path: str) -> None:
        with self._lock:
            s = self._sessions.get(session_id)
            if s:
                s["image_path"] = path

    def get_counts(self, session_id: str) -> dict:
        s = self._sessions.get(session_id)
        return s["counts"].copy() if s else DEFAULT_COUNTS.copy()


# ── Global instance ────────────────────────────────────────────
session_manager = SessionManager()
