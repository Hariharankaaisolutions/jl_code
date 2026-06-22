"""
scheduler/auto_start.py — Auto Start Scheduler
================================================
Starts detection session automatically at boot + delay.
Monitors session health and restarts on crash.
Max 100 lines. One responsibility: auto-start and monitor.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Optional

import httpx

from core.config import get, getint, getbool
from core.logger import get_logger
from core.log_codes import get as LOG
from scheduler.auto_stop import past_stop_time

logger = get_logger("AUTO")

ENABLED       = getbool("AUTOSTART_ENABLED",          True)
DELAY_MINS    = getint("AUTO_START_DELAY_MINS",        0)
AUTO_RESTART  = getbool("AUTO_START_RESTART",          True)
RESTART_DELAY = getint("AUTO_START_RESTART_DELAY_SECS", 30)
USER_ID       = get("AUTO_START_USER_ID",    "autostart")
VEHICLE       = get("AUTO_START_VEHICLE",    "XX00XX0000")
VIDEO_URL     = get("AUTO_START_VIDEO_URL",  "cam_1")
DEVICE_ID     = "JL-Z440-AUTO"
API_URL       = "http://127.0.0.1:8000"

_current_sid: Optional[str] = None
_current_tid: Optional[str] = None
_halted: bool = False


def set_halted(val: bool) -> None:
    global _halted
    _halted = val


def get_current_session() -> Optional[str]:
    return _current_sid


async def _start_session() -> tuple:
    sid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    payload = {
        "session_id": sid, "transaction_id": tid,
        "user_id": USER_ID, "device_unique_id": DEVICE_ID,
        "name": "AutoStarter", "role": "OPERATOR",
        "vehicle_number": VEHICLE, "video_url": VIDEO_URL,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{API_URL}/start", json=payload)
        if r.status_code == 200:
            logger.info(LOG("AUTO.004.INFO", session_id=sid[:8]))
            return True, sid, tid
        body = r.text[:200]
        if r.status_code == 400 and "already running" in body:
            logger.info(LOG("AUTO.006.INFO"))
            return None, "", ""
        logger.error(LOG("AUTO.005.ERROR", status=r.status_code, body=body))
        return False, "", ""
    except Exception as e:
        logger.error(LOG("AUTO.005.ERROR", status=0, body=str(e)))
        return False, "", ""


async def _is_active(sid: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(f"{API_URL}/status",
                             json={"session_id": sid})
        return r.json().get("active", False)
    except Exception:
        return False


async def _loop() -> None:
    global _current_sid, _current_tid

    if not ENABLED:
        logger.info(LOG("AUTO.012.INFO"))
        return

    wait = 10  # 10 seconds
    logger.info(LOG("AUTO.002.INFO", delay=DELAY_MINS,
        time=(datetime.now() + timedelta(seconds=wait)).strftime("%H:%M:%S")))

    try:
        from core.mailer import send_admin
        from scheduler.boot_report import send as send_boot
        asyncio.create_task(asyncio.to_thread(send_boot))
    except Exception:
        pass

    await asyncio.sleep(wait)

    session_count = 0
    while True:
        if past_stop_time():
            logger.info(LOG("AUTO.008.INFO", total_sessions=session_count))
            break
        if _halted:
            logger.info(LOG("AUTO.010.WARN"))
            await asyncio.sleep(30)
            continue

        logger.info(LOG("AUTO.003.INFO",
            session_id="new", tx_id="new"))
        ok, sid, tid = await _start_session()

        if ok is None:
            await asyncio.sleep(60)
            continue
        if not ok:
            logger.error(LOG("AUTO.009.INFO"))
            await asyncio.sleep(RESTART_DELAY)
            continue

        session_count += 1
        _current_sid  = sid
        _current_tid  = tid

        # Monitor session
        while True:
            await asyncio.sleep(10)
            if past_stop_time():
                break
            if _halted:
                break
            if not await _is_active(sid):
                logger.warning(f"Session ended: {sid[:8]}")
                break

        _current_sid = None
        _current_tid = None

        if past_stop_time() or not AUTO_RESTART or _halted:
            break

        logger.info(LOG("AUTO.009.INFO"))
        await asyncio.sleep(RESTART_DELAY)


def start() -> None:
    """Start auto-session loop as asyncio task."""
    if not ENABLED:
        logger.info(LOG("AUTO.012.INFO"))
        return
    asyncio.create_task(_loop())
    logger.info(LOG("AUTO.001.INFO"))
