# auto_stop_scheduler.py
# ─────────────────────────────────────────────────────────────────────────────
# Automatically stops all active detection sessions at a configured time.
#
# Config (config.properties in cam1_app_1 folder):
#   AUTO_STOP_ENABLED = true          # set false to disable
#   AUTO_STOP_TIME    = 19:55         # 24-hour HH:MM  (default 19:55 = 7:55 PM)
#
# Usage — call start_auto_stop_scheduler() once at app startup (e.g. in main.py)
# It runs a background asyncio task that:
#   1. Sleeps until the stop time
#   2. Calls session_manager.stop_session() for every active session
#   3. Sends an HTML alert mail to TO_EMAIL
#   4. Loops to next day
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from smart_logger import get_logger
from session import session_manager
from config_mail import EmailConfig          # same as used by session.py
import smtplib

logger = get_logger("auto_stop_scheduler")

# ── Load config ───────────────────────────────────────────────────────────────
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.properties")

def _load_props() -> dict:
    data = {}
    try:
        with open(_CONFIG_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return data


# ── HTML mail builder ─────────────────────────────────────────────────────────

def _build_html(stop_time_str: str, stopped_sessions: list[str], stop_dt: datetime) -> str:
    date_str     = stop_dt.strftime("%d %B %Y")
    weekday_str  = stop_dt.strftime("%A")
    time_display = stop_dt.strftime("%I:%M %p")   # e.g. 07:55 PM

    if stopped_sessions:
        session_rows = "".join(
            f"""<tr>
                  <td style="padding:10px 16px;font-size:14px;color:#1A237E;
                             font-family:'Courier New',monospace;
                             border-bottom:1px solid #ECEFF1;">
                    {s}
                  </td>
                </tr>"""
            for s in stopped_sessions
        )
        sessions_block = f"""
        <p style="margin:0 0 10px;font-size:11px;font-weight:700;
                   color:#90A4AE;letter-spacing:1px;text-transform:uppercase;">
          Sessions Stopped
        </p>
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border-radius:12px;border:1px solid #E3EAF0;
                      overflow:hidden;margin-bottom:24px;">
          <tr style="background:#ECEFF1;">
            <td style="padding:10px 16px;font-size:12px;font-weight:700;
                       color:#607D8B;text-transform:uppercase;letter-spacing:0.5px;">
              Session ID
            </td>
          </tr>
          {session_rows}
        </table>"""
    else:
        sessions_block = """
        <div style="background:#F1F8E9;border-radius:10px;
                    border-left:4px solid #8BC34A;padding:14px 18px;
                    margin-bottom:24px;">
          <p style="margin:0;color:#558B2F;font-size:14px;">
            ✅ No active sessions were running at the stop time.
          </p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Auto-Stop Alert</title>
</head>
<body style="margin:0;padding:0;background:#f0f4f8;
             font-family:'Segoe UI',Arial,sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f0f4f8;padding:40px 0;">
    <tr><td align="center">

      <!-- Card -->
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;
                    box-shadow:0 4px 24px rgba(0,0,0,0.08);overflow:hidden;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#4527A0,#311B92);
                      padding:28px 40px;text-align:center;">
            <div style="font-size:28px;margin-bottom:6px;">🛑</div>
            <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700;">
              Detection Auto-Stopped
            </h1>
            <p style="margin:6px 0 0;color:#D1C4E9;font-size:13px;">
              Scheduled shutdown — JL-CAM System
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px 40px;">

            <p style="margin:0 0 24px;color:#37474F;font-size:15px;line-height:1.6;">
              The JL-CAM detection system has been <strong>automatically stopped</strong>
              as per the configured daily shutdown time.
            </p>

            <!-- Info box -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#F8FAFB;border-radius:12px;
                          border:1px solid #E3EAF0;margin-bottom:28px;">
              <tr>
                <td style="padding:20px 24px;">
                  <p style="margin:0 0 12px;font-size:11px;font-weight:700;
                             color:#90A4AE;letter-spacing:1px;
                             text-transform:uppercase;">Shutdown Details</p>
                  <table width="100%" cellpadding="7" cellspacing="0">
                    <tr>
                      <td style="color:#78909C;font-size:14px;width:45%;">
                        📅 Date
                      </td>
                      <td style="color:#1A237E;font-size:14px;font-weight:600;">
                        {weekday_str}, {date_str}
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909C;font-size:14px;">
                        ⏰ Stop Time
                      </td>
                      <td style="color:#1A237E;font-size:14px;font-weight:600;">
                        {time_display}
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909C;font-size:14px;">
                        🔢 Sessions Stopped
                      </td>
                      <td style="color:#4527A0;font-size:14px;font-weight:700;">
                        {len(stopped_sessions)}
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            {sessions_block}

            <!-- Info note -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#EDE7F6;border-radius:10px;
                          border-left:4px solid #7E57C2;">
              <tr>
                <td style="padding:14px 18px;">
                  <p style="margin:0;color:#4527A0;font-size:13px;line-height:1.5;">
                    ℹ️ To change the stop time, update <strong>AUTO_STOP_TIME</strong>
                    in <code>config.properties</code> and restart the service.
                  </p>
                </td>
              </tr>
            </table>

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#F5F7FA;padding:18px 40px;
                      border-top:1px solid #ECEFF1;text-align:center;">
            <p style="margin:0;color:#90A4AE;font-size:12px;line-height:1.6;">
              This is an automated alert from <strong>JL-CAM System</strong>.<br>
              Please do not reply to this email.
            </p>
          </td>
        </tr>

      </table>
      <!-- /Card -->

    </td></tr>
  </table>
</body>
</html>"""


# ── Mail sender ───────────────────────────────────────────────────────────────

def _send_auto_stop_mail(stopped_sessions: list[str], stop_dt: datetime):
    try:
        cfg = EmailConfig()

        time_display = stop_dt.strftime("%I:%M %p")
        date_str     = stop_dt.strftime("%d %B %Y")
        subject      = f"🛑 JL-CAM Detection Auto-Stopped at {time_display} — {date_str}"

        plain = (
            f"JL-CAM Auto-Stop Alert\n\n"
            f"Detection was automatically stopped at {time_display} on {date_str}.\n"
            f"Sessions stopped: {len(stopped_sessions)}\n"
            + ("\n".join(f"  - {s}" for s in stopped_sessions) if stopped_sessions
               else "  (no active sessions)")
            + "\n\nThis is an automated notification from JL-CAM System."
        )

        msg = MIMEMultipart("alternative")
        msg["From"]    = cfg.smtp_username
        msg["To"]      = cfg.to_email
        msg["Subject"] = subject

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(_build_html(time_display, stopped_sessions, stop_dt), "html"))

        with smtplib.SMTP(cfg.smtp_server, cfg.smtp_port, timeout=20) as server:
            server.starttls()
            server.login(cfg.smtp_username, cfg.smtp_password)
            server.send_message(msg)

        logger.info(f"Auto-stop mail sent → {cfg.to_email}")

    except Exception:
        logger.exception("Auto-stop mail failed — sessions were still stopped")


# ── Core scheduler loop ───────────────────────────────────────────────────────

async def _scheduler_loop():
    while True:
        props = _load_props()

        enabled = props.get("AUTO_STOP_ENABLED", "true").lower() == "true"
        if not enabled:
            logger.info("AUTO_STOP_ENABLED=false — scheduler sleeping 60s")
            await asyncio.sleep(60)
            continue

        stop_time_str = props.get("AUTO_STOP_TIME", "19:55")

        try:
            stop_h, stop_m = map(int, stop_time_str.strip().split(":"))
        except ValueError:
            logger.error(f"Invalid AUTO_STOP_TIME='{stop_time_str}' — expected HH:MM. Retrying in 60s.")
            await asyncio.sleep(60)
            continue

        now       = datetime.now()
        stop_dt   = now.replace(hour=stop_h, minute=stop_m, second=0, microsecond=0)

        # If today's stop time already passed, schedule for tomorrow
        if now >= stop_dt:
            stop_dt += timedelta(days=1)

        wait_secs = (stop_dt - now).total_seconds()
        logger.info(
            f"Auto-stop scheduled at {stop_dt.strftime('%Y-%m-%d %H:%M')} "
            f"({wait_secs/60:.1f} min from now)"
        )

        await asyncio.sleep(wait_secs)

        # ── Re-read config at stop time (user may have changed it) ────
        props = _load_props()
        enabled = props.get("AUTO_STOP_ENABLED", "true").lower() == "true"
        if not enabled:
            logger.info("AUTO_STOP_ENABLED turned off — skipping this stop")
            continue

        # ── Stop all active sessions ──────────────────────────────────
        active_ids = list(session_manager.sessions.keys())
        stopped    = []

        for sid in active_ids:
            if session_manager.is_active(sid):
                try:
                    session_manager.stop_session(sid)
                    stopped.append(sid)
                    logger.info(f"Auto-stopped session: {sid}")
                except Exception:
                    logger.exception(f"Failed to auto-stop session: {sid}")

        logger.info(
            f"Auto-stop complete at {stop_dt.strftime('%H:%M')} — "
            f"{len(stopped)} session(s) stopped"
        )

        # ── Send HTML alert mail ──────────────────────────────────────
        _send_auto_stop_mail(stopped, stop_dt)

        # Sleep 90s before looping (avoids double-trigger at the same minute)
        await asyncio.sleep(90)


# ── Public entry point ────────────────────────────────────────────────────────

def start_auto_stop_scheduler():
    """
    Call this once at startup (e.g. in your main FastAPI startup handler).
    Spawns a background asyncio task — does not block.
    """
    asyncio.create_task(_scheduler_loop())
    logger.info("Auto-stop scheduler started")