# main_api.py — All FastAPI routes (/start, /stop, /status, /count)
# ==================================================================

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncio

from smart_logger import get_logger
logger = get_logger(__name__)

from session import session_manager
from mqtt_push import mqtt_push_error
from raw_video import start_raw_recording, stop_raw_recording
from message_loader import Messages

from main_config import RTMP_BASE_URL
from main_session_guard import any_active_session_exists
from main_detection import detect_objects

router = APIRouter()


# ------------------------------------------------------------------
# Request Models
# ------------------------------------------------------------------
class DetectionRequest(BaseModel):
    name: str
    role: str
    user_id: str
    device_unique_id: str
    vehicle_number: str
    video_url: str
    session_id: str
    transaction_id: str


class StopRequest(BaseModel):
    session_id: str
    transaction_id: str


class StatusRequest(BaseModel):
    session_id: str


# ------------------------------------------------------------------
# STATUS
# ------------------------------------------------------------------
@router.post("/status")
async def post_status(data: StatusRequest):
    """
    Check whether a session is currently active
    """
    try:
        active = session_manager.is_active(data.session_id)
        return {
            "session_id": data.session_id,
            "active": active
        }
    except Exception:
        logger.exception(Messages.get("API.STATUS.001.ERROR"))
        raise HTTPException(status_code=500, detail="Status check failed")


# ------------------------------------------------------------------
# START
# ------------------------------------------------------------------
@router.post("/start")
async def start_detection(data: DetectionRequest):
    logger.debug("Received /start request payload: %s", data.dict())

    try:
        logger.info(
            Messages.get(
                "SESSION.START.001.INFO",
                session_id=data.session_id,
            )
        )

        # ---- Validation ----
        if not data.transaction_id:
            logger.warning(
                Messages.get(
                    "SESSION.START.002.WARN",
                    session_id=data.session_id,
                )
            )
            raise HTTPException(status_code=400, detail="Transaction ID is required")

        if not session_manager.db.user_exists(
            data.user_id, data.device_unique_id
        ):
            logger.warning(
                Messages.get(
                    "SESSION.START.003.WARN",
                    user_id=data.user_id,
                    device_id=data.device_unique_id,
                )
            )
            raise HTTPException(status_code=404, detail="User not found")

        # ---- Single-session lock ----
        if any_active_session_exists():
            logger.error(
                Messages.get(
                    "SESSION.START.005.ERROR",
                    session_id=data.session_id
                )
            )
            raise HTTPException(
                status_code=400,
                detail="Another detection session is already running. Stop it first.",
            )

        if session_manager.session_exists(data.session_id):
            logger.warning(
                Messages.get(
                    "SESSION.START.004.WARN",
                    session_id=data.session_id,
                )
            )
            raise HTTPException(status_code=400, detail="Session already running")

        # ---- Resolve RTMP URL ----
        stream_url = f"{RTMP_BASE_URL}{data.video_url}"
        logger.debug(
            "Resolved stream_url=%s for provided video_url=%s",
            stream_url, data.video_url
        )

        # ---- Start Session ----
        session_manager.start_session(
            session_id=data.session_id,
            name=data.name,
            role=data.role,
            user_id=data.user_id,
            device_unique_id=data.device_unique_id,
            vehicle_number=data.vehicle_number,
            video_url=stream_url,
            transaction_id=data.transaction_id,
        )

        # ---- Start RAW Recording ----
        try:
            start_raw_recording(data.transaction_id, stream_url)
            logger.info(
                "RAW recording started for transaction=%s",
                data.transaction_id
            )
        except Exception:
            logger.exception("Failed to start RAW RTMP recording")

        # ---- Start Detection Task ----
        asyncio.create_task(
            detect_objects(stream_url, data.session_id)
        )

        logger.info(
            Messages.get(
                "SESSION.START.007.INFO",
                session_id=data.session_id,
            )
        )

        return {
            "message": "Detection started",
            "session_id": data.session_id,
            "transaction_id": data.transaction_id,
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(
            Messages.get(
                "SESSION.START.006.ERROR",
                session_id=getattr(data, "session_id", None),
            )
        )
        try:
            mqtt_push_error(
                session_id=data.session_id,
                transaction_id=data.transaction_id,
                error_code="START_DETECTION_ERROR",
                message=str(e),
                severity="high",
            )
        except Exception:
            logger.exception("Failed to push START_DETECTION_ERROR MQTT error")

        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------
# STOP
# ------------------------------------------------------------------
@router.post("/stop")
async def stop_detection(data: StopRequest):
    logger.debug("Received /stop payload: %s", data.dict())

    try:
        if not data.transaction_id:
            logger.warning(Messages.get("SESSION.STOP.006.ERROR"))
            raise HTTPException(
                status_code=400,
                detail="Transaction ID required"
            )

        if not session_manager.session_exists(data.session_id):
            logger.warning(
                Messages.get(
                    "SESSION.STOP.007.ERROR",
                    session_id=data.session_id,
                )
            )
            raise HTTPException(status_code=404, detail="Session not found")

        # ---- Stop Session ----
        session_manager.stop_session(data.session_id)
        logger.info(
            "🛑 Stop request processed for session=%s",
            data.session_id
        )

        # ---- Stop RAW Recording ----
        try:
            stop_raw_recording(data.transaction_id)
            logger.info(
                "RAW recording stopped for transaction=%s",
                data.transaction_id
            )
        except Exception:
            logger.exception("Failed to stop RAW RTMP recording")

        return {
            "message": "Detection stopped",
            "transaction_id": data.transaction_id
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(Messages.get("SESSION.STOP.008.ERROR"))
        try:
            mqtt_push_error(
                session_id=data.session_id,
                transaction_id=data.transaction_id,
                error_code="STOP_DETECTION_ERROR",
                message=str(e),
                severity="medium",
            )
        except Exception:
            logger.exception("Failed to push STOP_DETECTION_ERROR MQTT error")

        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------
# COUNT
# ------------------------------------------------------------------
@router.get("/count/{session_id}")
async def get_detection_count(session_id: str):
    logger.debug("Received /count request for session=%s", session_id)

    if not session_manager.session_exists(session_id):
        logger.warning(
            Messages.get(
                "API.COUNT.001.WARN",
                session_id=session_id,
            )
        )
        raise HTTPException(status_code=404, detail="Session not found")

    counts = session_manager.get_counts(session_id)
    logger.debug(
        "Returning counts for session=%s -> %s",
        session_id, counts
    )

    return {
        "session_id": session_id,
        "counts": counts,
    }
