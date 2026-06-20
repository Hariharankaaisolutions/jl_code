# auto_start_session.py — Auto Session Manager
# =============================================
# Runs as background asyncio task inside CAM1 API
#
# Flow:
#   1. Boot → wait AUTO_START_DELAY_MINS (default 10 min)
#   2. Send boot report email
#   3. Start detection session automatically
#   4. If session crashes → wait AUTO_START_RESTART_DELAY_SECS → restart
#   5. Keep restarting until AUTO_STOP_TIME (18:00)
#   6. Halt command via MQTT → stop restart loop
#   7. Resume command via MQTT → re-enable restart loop
# =============================================

import asyncio
import os
import uuid
import httpx
from datetime import datetime, timedelta
from typing import Optional

from jl_logger import get_logger, log_separator
from mqtt_control import is_halted, publish_error, register_callbacks

logger = get_logger("AUTOSTART")

# ─────────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────────
_PROPS_FILE = os.path.join(os.path.dirname(__file__), "app.properties")

def _load_props() -> dict:
    props = {}
    try:
        with open(_PROPS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
    except Exception:
        pass
    return props

_props = _load_props()

ENABLED              = _props.get("AUTO_START_ENABLED",         "true").lower() == "true"
DELAY_MINS           = int(_props.get("AUTO_START_DELAY_MINS",  "10"))
USER_ID              = _props.get("AUTO_START_USER_ID",          "autostart")
VEHICLE              = _props.get("AUTO_START_VEHICLE",          "XX00XX0000")
VIDEO_URL            = _props.get("AUTO_START_VIDEO_URL",        "cam_1")
AUTO_RESTART         = _props.get("AUTO_START_RESTART",          "true").lower() == "true"
RESTART_DELAY_SECS   = int(_props.get("AUTO_START_RESTART_DELAY_SECS", "30"))
AUTO_STOP_TIME       = _props.get("AUTO_STOP_TIME",             "18:00")
DEVICE_ID            = "JL-Z440-AUTO"
CAM1_API_URL         = "http://127.0.0.1:8000"

# ─────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────
_current_session_id:     Optional[str] = None
_current_transaction_id: Optional[str] = None
_force_restart:          bool          = False
_running:                bool          = False

def get_current_session() -> Optional[str]:
    return _current_session_id

# ─────────────────────────────────────────────────
# Auto-stop time parser
# ─────────────────────────────────────────────────
def _get_stop_dt() -> datetime:
    """Get today's auto-stop datetime."""
    try:
        h, m = map(int, AUTO_STOP_TIME.strip().split(":"))
        now  = datetime.now()
        stop = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if now >= stop:
            stop += timedelta(days=1)
        return stop
    except Exception:
        logger.error(f"Invalid AUTO_STOP_TIME='{AUTO_STOP_TIME}' — defaulting to 18:00")
        now = datetime.now()
        return now.replace(hour=18, minute=0, second=0, microsecond=0)

def _past_stop_time() -> bool:
    """Returns True if current time is past AUTO_STOP_TIME."""
    try:
        h, m = map(int, AUTO_STOP_TIME.strip().split(":"))
        now  = datetime.now()
        stop = now.replace(hour=h, minute=m, second=0, microsecond=0)
        return now >= stop
    except Exception:
        return False

# ─────────────────────────────────────────────────
# Session start via CAM1 API
# ─────────────────────────────────────────────────
async def _start_session() -> tuple[bool, str, str]:
    """
    POST /start to CAM1 API.
    Returns (success, session_id, transaction_id).
    """
    session_id     = str(uuid.uuid4())
    transaction_id = str(uuid.uuid4())

    payload = {
        "session_id":       session_id,
        "transaction_id":   transaction_id,
        "user_id":          USER_ID,
        "device_unique_id": DEVICE_ID,
        "name":             "AutoStarter",
        "role":             "OPERATOR",
        "vehicle_number":   VEHICLE,
        "video_url":        VIDEO_URL,
    }

    logger.info(
        f"Starting auto-session → "
        f"session={session_id[:8]} tx={transaction_id[:8]} "
        f"vehicle={VEHICLE} video={VIDEO_URL}"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{CAM1_API_URL}/start", json=payload)

        if resp.status_code == 200:
            logger.info(
                f"Auto-session started successfully → "
                f"session={session_id[:8]} tx={transaction_id[:8]}"
            )
            return True, session_id, transaction_id
        else:
            body = resp.text[:200]
            # If session already running — not an error, just return special flag
            if resp.status_code == 400 and "already running" in body:
                logger.info(
                    f"Auto-session: session already running — will monitor existing session"
                )
                return None, "", ""
            logger.error(
                f"Auto-session start failed → "
                f"status={resp.status_code} body={body}"
            )
            publish_error(
                "AUTO_START_FAILED",
                f"Session start returned {resp.status_code}: {body}",
                severity="high"
            )
            return False, "", ""

    except httpx.ConnectError as e:
        logger.error(f"Auto-session start — API not reachable: {e}")
        return False, "", ""
    except Exception as e:
        logger.error(f"Auto-session start failed: {e}", exc_info=True)
        return False, "", ""


# ─────────────────────────────────────────────────
# Session stop via CAM1 API
# ─────────────────────────────────────────────────
async def _stop_session(session_id: str) -> bool:
    """POST /stop to CAM1 API."""
    if not session_id:
        return True
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{CAM1_API_URL}/stop",
                json={"session_id": session_id}
            )
        if resp.status_code == 200:
            logger.info(f"Auto-session stopped → session={session_id[:8]}")
            return True
        else:
            logger.warning(
                f"Auto-session stop returned {resp.status_code} "
                f"for session={session_id[:8]}"
            )
            return False
    except Exception as e:
        logger.error(f"_stop_session failed: {e}", exc_info=True)
        return False


# ─────────────────────────────────────────────────
# Check if session is still active
# ─────────────────────────────────────────────────
async def _is_session_active(session_id: str) -> bool:
    """Check if session is still active via session_manager directly."""
    try:
        from session import session_manager
        return session_manager.is_active(session_id)
    except Exception:
        return False


# ─────────────────────────────────────────────────
# MQTT control callbacks
# ─────────────────────────────────────────────────
def _on_halt():
    logger.warning(
        "HALT received → auto-restart DISABLED. "
        "Current session will finish naturally."
    )

def _on_resume():
    logger.info("RESUME received → auto-restart RE-ENABLED")

def _on_restart():
    global _force_restart
    _force_restart = True
    logger.info("RESTART command received → forcing session restart")


# ─────────────────────────────────────────────────
# Main auto-start loop
# ─────────────────────────────────────────────────
async def _auto_start_loop():
    global _current_session_id, _current_transaction_id, _force_restart, _running
    _running = True

    log_separator("AUTOSTART", "AUTO START LOOP STARTING")

    # Register MQTT callbacks
    register_callbacks(
        on_halt=_on_halt,
        on_resume=_on_resume,
        on_restart=_on_restart,
    )

    if not ENABLED:
        logger.info("AUTO_START_ENABLED=false — auto-start loop not running")
        return

    # ── Wait for initial delay ──────────────────────────────────────────
    wait_secs = DELAY_MINS * 60
    start_dt  = datetime.now() + timedelta(seconds=wait_secs)
    logger.info(
        f"Auto-start waiting {DELAY_MINS} min → "
        f"first session at {start_dt.strftime('%H:%M:%S')}"
    )

    # During wait — send boot report
    try:
        from boot_report import send_boot_report
        logger.info("Sending boot report email...")
        asyncio.create_task(asyncio.to_thread(send_boot_report))
    except Exception as e:
        logger.error(f"Boot report task failed: {e}", exc_info=True)

    await asyncio.sleep(wait_secs)

    # ── Main session loop ───────────────────────────────────────────────
    session_count = 0

    while True:
        # Check stop time
        if _past_stop_time():
            logger.info(
                f"AUTO_STOP_TIME={AUTO_STOP_TIME} reached — "
                f"auto-start loop stopping. Total sessions: {session_count}"
            )
            log_separator("AUTOSTART", "AUTO START LOOP STOPPED")
            break

        # Check halt
        if is_halted():
            logger.info(
                "Halt active — waiting for RESUME command. "
                "Checking every 30s..."
            )
            await asyncio.sleep(30)
            continue

        # Start session
        log_separator("AUTOSTART", f"SESSION {session_count + 1} STARTING")
        ok, sid, tid = await _start_session()

        if ok is None:
            # Session already running — wait and monitor
            logger.info("Session already running — waiting 60s before checking again")
            await asyncio.sleep(60)
            continue

        if not ok:
            logger.error(
                f"Session start failed — retrying in {RESTART_DELAY_SECS}s"
            )
            await asyncio.sleep(RESTART_DELAY_SECS)
            continue

        session_count              += 1
        _current_session_id         = sid
        _current_transaction_id     = tid
        _force_restart              = False

        logger.info(
            f"Session {session_count} running → "
            f"session={sid[:8]} tx={tid[:8]}"
        )

        # ── Monitor session until it ends ──────────────────────────────
        poll_interval = 10  # seconds
        session_start = datetime.now()

        while True:
            await asyncio.sleep(poll_interval)

            # Force restart requested via MQTT
            if _force_restart:
                logger.info("Force restart requested — stopping current session")
                await _stop_session(sid)
                _force_restart = False
                break

            # Check stop time
            if _past_stop_time():
                logger.info(
                    f"AUTO_STOP_TIME={AUTO_STOP_TIME} reached — "
                    f"stopping current session"
                )
                await _stop_session(sid)
                break

            # Check halt
            if is_halted():
                logger.warning(
                    "Halt command received — stopping session, "
                    "disabling auto-restart"
                )
                await _stop_session(sid)
                break

            # Check if session is still active
            active = await _is_session_active(sid)
            if not active:
                elapsed = (datetime.now() - session_start).total_seconds()
                # Send crash alert email
                try:
                    from alert_manager import alert_session_crash
                    alert_session_crash(
                        session_id=sid,
                        transaction_id=_current_transaction_id or "unknown",
                        duration_secs=duration,
                        error="Session active=False — NO_FRAMES or connection dropped",
                        restart_in=RESTART_DELAY_SECS,
                    )
                except Exception as ae:
                    logger.error(f"Alert send failed: {ae}")

                logger.warning(
                    f"Session ended unexpectedly → "
                    f"session={sid[:8]} "
                    f"duration={elapsed:.0f}s ({elapsed/60:.1f}min)"
                )
                publish_error(
                    "SESSION_CRASHED",
                    f"Session {sid[:8]} ended after {elapsed:.0f}s",
                    severity="high"
                )
                break

        _current_session_id     = None
        _current_transaction_id = None


        # ── Clean up stuck session from session_manager ────────────────
        try:
            from session import session_manager
            for stuck_sid in list(session_manager.sessions.keys()):
                try:
                    if session_manager.sessions[stuck_sid].get('active', False):
                        session_manager.sessions[stuck_sid]['active'] = False
                        logger.info(f'Cleaned stuck session: {stuck_sid[:8]}')
                except Exception:
                    pass
        except Exception as e:
            logger.error(f'Session cleanup failed: {e}', exc_info=True)
        # ── Decide whether to restart ──────────────────────────────────
        if _past_stop_time():
            logger.info("Past stop time — not restarting")
            break

        if is_halted():
            logger.info("Halted — not restarting")
            continue

        if not AUTO_RESTART:
            logger.info("AUTO_START_RESTART=false — not restarting")
            break

        logger.info(
            f"Restarting in {RESTART_DELAY_SECS}s... "
            f"(session {session_count} complete)"
        )
        await asyncio.sleep(RESTART_DELAY_SECS)

    _running = False
    log_separator("AUTOSTART", "AUTO START LOOP ENDED")


# ─────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────
def start_auto_session():
    """
    Start auto-session background task.
    Call once at FastAPI startup after MQTT is connected.
    """
    if not ENABLED:
        logger.info("AUTO_START_ENABLED=false — skipping auto-session")
        return

    asyncio.create_task(_auto_start_loop())
    logger.info(
        f"Auto-session task created → "
        f"delay={DELAY_MINS}min "
        f"vehicle={VEHICLE} "
        f"stop_at={AUTO_STOP_TIME} "
        f"restart={AUTO_RESTART}"
    )

