"""
scheduler/housekeeping.py — Daily Housekeeping
================================================
Deletes old videos, detected frames, RL frames, logs.
Runs daily at HOUSEKEEPING_TIME (default 20:30).
Max 100 lines. One responsibility: clean old files.
"""

import os
import time
import asyncio
import threading
from datetime import datetime, timedelta
from pathlib import Path

from core.config import get, getint, getbool
from core.logger import get_logger
from core.log_codes import get as LOG
from core.mailer import send_admin

logger = get_logger("HOUSE")

ENABLED      = getbool("HOUSEKEEPING_ENABLED", True)
HK_TIME      = get("HOUSEKEEPING_TIME", "20:30")
VID_DAYS     = getint("VIDEO_KEEP_DAYS",           10)
FRAME_DAYS   = getint("DETECTED_FRAMES_KEEP_DAYS", 30)
RL_DAYS      = getint("RL_FRAMES_KEEP_DAYS",       100)
LOG_DAYS     = getint("LOGS_KEEP_DAYS",            45)

CAM1_VID     = get("CAM1_VIDEO_BASE_DIR", "/opt/secure_ai/cam1/video")
CAM2_VID     = get("CAM2_VIDEO_BASE_DIR", "/opt/secure_ai/cam2/video")
FRAMES_DIR   = get("DETECTED_FRAMES_DIR", "/opt/secure_ai/database/detected_frames")
RL_DIR       = get("RL_SAVE_DIR",         "/opt/secure_ai/reinforcement_learning")
LOG_DIR      = get("LOG_DIR",             "/var/log/smartcounter")


def _delete_old_files(folder: str, days: int, label: str) -> int:
    """Delete files older than N days. Returns count deleted."""
    deleted  = 0
    cutoff   = time.time() - days * 86400
    try:
        for root, dirs, files in os.walk(folder):
            for f in files:
                path = os.path.join(root, f)
                try:
                    if os.path.getmtime(path) < cutoff:
                        age = int((time.time() - os.path.getmtime(path)) / 86400)
                        os.remove(path)
                        deleted += 1
                        logger.info(LOG(f"HOUSE.003.INFO", path=path, age=age))
                except Exception as e:
                    logger.error(LOG("HOUSE.007.ERROR", error=e))
        # Remove empty dirs
        for root, dirs, files in os.walk(folder, topdown=False):
            for d in dirs:
                dp = os.path.join(root, d)
                try:
                    if not os.listdir(dp):
                        os.rmdir(dp)
                except Exception:
                    pass
    except Exception as e:
        logger.error(LOG("HOUSE.007.ERROR", error=e))
    return deleted


def run() -> dict:
    """Run housekeeping. Returns summary dict."""
    logger.info(LOG("HOUSE.001.INFO", time=datetime.now().strftime("%H:%M")))

    v1  = _delete_old_files(CAM1_VID,   VID_DAYS,   "cam1 video")
    v2  = _delete_old_files(CAM2_VID,   VID_DAYS,   "cam2 video")
    f   = _delete_old_files(FRAMES_DIR, FRAME_DAYS, "detected frames")
    rl  = _delete_old_files(RL_DIR,     RL_DAYS,    "RL frames")
    lg  = _delete_old_files(LOG_DIR,    LOG_DAYS,   "logs")

    total_vid = v1 + v2
    result = {
        "videos": total_vid, "frames": f,
        "rl": rl, "logs": lg,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    logger.info(LOG("HOUSE.002.INFO",
        deleted_videos=total_vid, deleted_frames=f,
        deleted_rl=rl, deleted_logs=lg))

    _send_report(result)
    return result


def _send_report(result: dict) -> None:
    subject = f"🧹 JL-CAM Housekeeping Complete — {result['time']}"
    html = f"""
    <div style="font-family:Arial;padding:20px;">
      <h2 style="color:#1B5E20;">🧹 JL-CAM Daily Housekeeping</h2>
      <table style="border-collapse:collapse;width:100%;">
        <tr><td style="padding:8px;color:#666;">📹 Videos deleted</td>
            <td style="padding:8px;font-weight:bold;">{result['videos']}</td></tr>
        <tr style="background:#F1F8E9;">
            <td style="padding:8px;color:#666;">🖼️ Detected frames deleted</td>
            <td style="padding:8px;font-weight:bold;">{result['frames']}</td></tr>
        <tr><td style="padding:8px;color:#666;">🔬 RL frames deleted</td>
            <td style="padding:8px;font-weight:bold;">{result['rl']}</td></tr>
        <tr style="background:#F1F8E9;">
            <td style="padding:8px;color:#666;">📄 Logs deleted</td>
            <td style="padding:8px;font-weight:bold;">{result['logs']}</td></tr>
        <tr><td style="padding:8px;color:#666;">🕐 Time</td>
            <td style="padding:8px;">{result['time']}</td></tr>
      </table>
    </div>"""
    if getbool("EMAIL_HOUSEKEEPING", True):
        send_admin(subject, html)
        logger.info(LOG("HOUSE.009.INFO"))


async def _scheduler_loop() -> None:
    while True:
        if not getbool("HOUSEKEEPING_ENABLED", True):
            logger.info(LOG("HOUSE.008.WARN"))
            await asyncio.sleep(3600)
            continue
        try:
            h, m   = map(int, HK_TIME.split(":"))
            now    = datetime.now()
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            wait = (target - now).total_seconds()
            logger.info(f"Housekeeping scheduled at {target.strftime('%H:%M')} "
                        f"({wait/60:.0f} min from now)")
            await asyncio.sleep(wait)
            run()
        except Exception as e:
            logger.error(LOG("HOUSE.007.ERROR", error=e))
            await asyncio.sleep(3600)


def start() -> None:
    """Start housekeeping scheduler as asyncio task."""
    asyncio.create_task(_scheduler_loop())
    logger.info(f"Housekeeping scheduler started → time={HK_TIME}")
