# main_session_guard.py — Single Session Lock
# ===========================================

from smart_logger import get_logger
logger = get_logger(__name__)

from session import session_manager
from message_loader import Messages


def any_active_session_exists() -> bool:
    """
    Prevents multiple detection sessions from running.
    Returns True if any session is active.
    """
    try:
        for session_id in session_manager.sessions.keys():
            try:
                if session_manager.is_active(session_id):
                    logger.warning(
                        Messages.get(
                            "CAMERA.SESSION.001.WARN",
                            session_id=session_id
                        )
                    )
                    return True
            except Exception:
                return True
        return False
    except Exception:
        return True
