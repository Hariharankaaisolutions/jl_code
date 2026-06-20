"""
scheduler/auto_stop.py — Auto Stop Scheduler
==============================================
Stops all active sessions at WORKING_HOURS_END (18:00).
Triggers segment drain, merge, and stop email.
Max 80 lines. One responsibility: auto-stop at configured time.
"""

import asyncio
from datetime import datetime, timedelta

from core.config import get, getbool
from core.logger import get_logger
from core.log_codes import get as LOG

logger   = get_logger("STOP")
STOP_TIME = get("WORKING_HOURS_END", "18:00")


def _get_stop_dt() -> datetime:
    try:
        h, m = map(int, STOP_TIME.split(":"))
        now  = datetime.now()
        dt   = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if now >= dt:
            dt += timedelta(days=1)
        return dt
    except Exception:
        now = datetime.now()
        return now.replace(hour=18, minute=0, second=0, microsecond=0)


def past_stop_time() -> bool:
    try:
        h, m = map(int, STOP_TIME.split(":"))
        now  = datetime.now()
        return now >= now.replace(hour=h, minute=m, second=0, microsecond=0)
    except Exception:
        return False


async def _stop_all_sessions() -> list:
    """Stop all active sessions via session manager."""
    stopped = []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get("http://127.0.0.1:8000/active_sessions")
            if resp.status_code == 200:
                sessions = resp.json().get("sessions", [])
                for s in sessions:
                    stop_resp = await client.post("http://127.0.0.1:8000/stop",
                        json={"session_id": s["session_id"],
                              "transaction_id": s["transaction_id"]})
                    if stop_resp.status_code == 200:
                        stopped.append(s["session_id"])
                        logger.info(LOG("STOP.003.INFO",
                            session_id=s["session_id"][:8]))
                    else:
                        logger.error(LOG("STOP.004.ERROR",
                            session_id=s["session_id"][:8],
                            error=stop_resp.text))
    except Exception as e:
        logger.error(LOG("STOP.004.ERROR", session_id="all", error=e))
    return stopped


async def _scheduler_loop() -> None:
    while True:
        stop_dt   = _get_stop_dt()
        wait_secs = (stop_dt - datetime.now()).total_seconds()
        logger.info(LOG("STOP.001.INFO", time=STOP_TIME))
        logger.info(f"Auto-stop in {wait_secs/60:.1f} min at "
                    f"{stop_dt.strftime('%H:%M')}")

        await asyncio.sleep(wait_secs)

        logger.info(LOG("STOP.002.INFO", time=datetime.now().strftime("%H:%M")))
        stopped = await _stop_all_sessions()

        logger.info(LOG("STOP.005.INFO", count=len(stopped)))

        from core.mailer import send_admin
        if getbool("EMAIL_AUTO_STOP", True):
            now  = datetime.now()
            subj = f"🛑 JL-CAM Auto-Stopped at {now.strftime('%I:%M %p')} — {now.strftime('%d %b %Y')}"
            html = f"""
            <div style="font-family:Arial;padding:20px;">
              <h2 style="color:#4527A0;">🛑 Detection Auto-Stopped</h2>
              <p>Scheduled stop at <strong>{STOP_TIME}</strong></p>
              <p>Sessions stopped: <strong>{len(stopped)}</strong></p>
              <p>Time: {now.strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>"""
            send_admin(subj, html)
            logger.info(LOG("STOP.006.INFO"))

        await asyncio.sleep(90)


def start() -> None:
    """Start auto-stop scheduler as asyncio task."""
    asyncio.create_task(_scheduler_loop())
    logger.info(LOG("STOP.001.INFO", time=STOP_TIME))
