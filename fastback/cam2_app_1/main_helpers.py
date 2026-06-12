# main_helpers.py — Misc Utility Helpers
# =====================================

from typing import Optional
from smart_logger import get_logger

logger = get_logger(__name__)

from session import session_manager
from message_loader import Messages


# -------------------------------------------------
# Transaction ID Helper
# -------------------------------------------------
def get_transaction_id(session_id: str) -> Optional[str]:
    """
    Safely fetch transaction_id for a session.
    Returns None if not found or on error.
    """
    try:
        sess = session_manager.sessions.get(session_id)
        if not sess:
            logger.debug(
                "No session found while fetching transaction_id (session_id=%s)",
                session_id,
            )
            return None

        return sess.get("transaction_id")

    except Exception:
        logger.exception(
            Messages.get("SESSION.TXID.001.ERROR", session_id=session_id)
        )
        return None


# -------------------------------------------------
# Session Validity Check
# -------------------------------------------------
def is_session_valid(session_id: str) -> bool:
    """
    Check whether a session exists and is currently active.
    """
    try:
        if not session_manager.session_exists(session_id):
            logger.debug(
                "Session does not exist (session_id=%s)",
                session_id,
            )
            return False

        return session_manager.is_active(session_id)

    except Exception:
        logger.exception(
            "Failed to validate session (session_id=%s)",
            session_id,
        )
        return False
