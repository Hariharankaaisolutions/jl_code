"""
cam1/api/routes.py — CAM1 API Routes
=======================================
FastAPI routes: /start /stop /status /count /active_sessions
Handles both auto session and virtual mobile sessions.
Max 150 lines. One responsibility: API endpoints.
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.config import get, getbool
from core.logger import get_logger
from core.log_codes import get as LOG
from cam1.api.session_manager import session_manager
from cam1.api import virtual_session as vs
from scheduler.auto_stop import past_stop_time

logger = get_logger("API")
router = APIRouter()

AUTOSTART_ENABLED = getbool("AUTOSTART_ENABLED", True)
START_TIME        = get("WORKING_HOURS_START", "08:00")
STOP_TIME         = get("WORKING_HOURS_END",   "18:00")

# ── Active detectors registry ──────────────────────────────────
_detectors: dict = {}
_recorders: dict = {}


# ── Request models ─────────────────────────────────────────────
class StartRequest(BaseModel):
    session_id:       str
    transaction_id:   str
    user_id:          str
    device_unique_id: str
    name:             str
    role:             str
    vehicle_number:   str
    video_url:        str


class StopRequest(BaseModel):
    session_id:     str
    transaction_id: str


class StatusRequest(BaseModel):
    session_id: str


# ── Helpers ────────────────────────────────────────────────────
def _is_within_hours() -> bool:
    now = datetime.now()
    try:
        sh, sm = map(int, START_TIME.split(":"))
        eh, em = map(int, STOP_TIME.split(":"))
        start  = now.replace(hour=sh, minute=sm, second=0)
        end    = now.replace(hour=eh, minute=em, second=0)
        return start <= now <= end
    except Exception:
        return True


def _is_auto_session(user_id: str) -> bool:
    return user_id == "autostart"


# ── Routes ─────────────────────────────────────────────────────
@router.post("/start")
async def start_detection(data: StartRequest):
    logger.info(LOG("API.002.INFO", session_id=data.session_id[:8]))

    # Block outside working hours
    if not _is_within_hours():
        logger.warning(LOG("API.008.WARN"))
        raise HTTPException(status_code=400,
            detail="Detection not available outside working hours "
                   f"({START_TIME}–{STOP_TIME})")

    # Auto session — real detection
    if _is_auto_session(data.user_id):
        if session_manager.any_active():
            raise HTTPException(status_code=400,
                detail="Another detection session is already running. "
                       "Stop it first.")
        ok = session_manager.start(
            session_id=data.session_id,
            transaction_id=data.transaction_id,
            name=data.name, role=data.role,
            user_id=data.user_id,
            device_id=data.device_unique_id,
            vehicle_number=data.vehicle_number,
            cam=data.video_url,
        )
        if not ok:
            raise HTTPException(status_code=400,
                detail="Session already running")

        # Start real detector + recorder
        from cam1.detection.live_detector import LiveDetector
        import cam1.recording.segment_recorder as rec

        def _on_count(sid, counts):
            session_manager.update_counts(sid, counts)

        detector = LiveDetector(
            session_id=data.session_id,
            transaction_id=data.transaction_id,
            cam=data.video_url,
            on_count=_on_count,
        )
        detector.start()
        _detectors[data.session_id] = detector

        raw_dir = rec.start(data.transaction_id)
        _recorders[data.transaction_id] = rec.get(data.transaction_id)

        logger.info(LOG("SESS.002.INFO",
            session_id=data.session_id[:8],
            tx_id=data.transaction_id[:8]))
        return {"message": "Detection started",
                "session_id": data.session_id,
                "transaction_id": data.transaction_id}

    # Mobile user — virtual session
    if vs.has_active(data.user_id):
        logger.warning(LOG("API.009.WARN"))
        raise HTTPException(status_code=400,
            detail="You already have an active session. Stop it first.")

    real_counts = {}
    active = session_manager.get_active_sessions()
    if active:
        real_counts = session_manager.get_counts(active[0]["session_id"])

    ok = vs.start(
        user_id=data.user_id,
        transaction_id=data.transaction_id,
        session_id=data.session_id,
        name=data.name, role=data.role,
        device_id=data.device_unique_id,
        vehicle_number=data.vehicle_number,
        cam=data.video_url,
        real_counts=real_counts,
    )
    if not ok:
        raise HTTPException(status_code=400,
            detail="Could not start virtual session")

    logger.info(LOG("SESS.013.INFO",
        user_id=data.user_id, tx_id=data.transaction_id[:8]))
    return {"message": "Detection started",
            "session_id": data.session_id,
            "transaction_id": data.transaction_id}


@router.post("/stop")
async def stop_detection(data: StopRequest):
    logger.info(LOG("API.003.INFO", session_id=data.session_id[:8]))

    # Auto session stop
    if session_manager.exists(data.session_id):
        detector = _detectors.pop(data.session_id, None)
        if detector:
            detector.stop()

        recorder = _recorders.pop(data.transaction_id, None)
        import cam1.recording.segment_recorder as rec_mod
        recorder = rec_mod.stop(data.transaction_id)

        s = session_manager.stop(data.session_id)
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")

        # Merge segments
        if recorder:
            import cam1.recording.segment_merger as merger
            merger.merge_background(
                transaction_id=data.transaction_id,
                date_dir=recorder.get_date_dir(),
                raw_segments=recorder.get_segments(),
            )
        return {"message": "Detection stopped",
                "transaction_id": data.transaction_id}

    # Virtual session stop — find by transaction_id
    for user_id, vs_data in vs._virtual.items():
        if vs_data.get("transaction_id") == data.transaction_id:
            active = session_manager.get_active_sessions()
            real_counts = (session_manager.get_counts(active[0]["session_id"])
                          if active else {})
            result = vs.stop(user_id, real_counts)
            if result:
                return {"message": "Detection stopped",
                        "transaction_id": data.transaction_id}

    raise HTTPException(status_code=404, detail="Session not found")


@router.post("/status")
async def get_status(data: StatusRequest):
    active = session_manager.is_active(data.session_id)
    logger.info(LOG("API.004.INFO", session_id=data.session_id[:8]))
    return {"session_id": data.session_id, "active": active}


@router.get("/count/{session_id}")
async def get_count(session_id: str):
    logger.info(LOG("API.005.INFO", session_id=session_id[:8]))
    if not session_manager.exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id,
            "counts": session_manager.get_counts(session_id)}


@router.get("/active_sessions")
async def get_active_sessions():
    return {"sessions": session_manager.get_active_sessions()}


@router.get("/health")
async def health():
    return {"status": "ok", "cam": "cam1",
            "time": datetime.now().isoformat()}


@router.get("/status")
async def get_status_get(session_id: str = ""):
    """GET /status for backward compatibility with smartclient."""
    if not session_id:
        return {"status": "running", "cam": "cam1",
                "active_sessions": len(session_manager.get_active_sessions())}
    active = session_manager.is_active(session_id)
    return {"session_id": session_id, "active": active}
