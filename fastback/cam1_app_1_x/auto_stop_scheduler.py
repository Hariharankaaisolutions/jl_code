# auto_stop_scheduler.py
# ─────────────────────────────────────────────────────────────────────────────
# Automatically stops all active detection sessions at a configured time.
# Raw video recording continues until RAW_VIDEO_AUTO_STOP_TIME.
#
# Config (app.properties):
#   AUTO_STOP_ENABLED        = true    # set false to disable
#   AUTO_STOP_TIME           = 18:00   # 24-hour HH:MM — stops detection only
#   RAW_VIDEO_AUTO_STOP_TIME = 19:30   # 24-hour HH:MM — stops raw recording
#
# Usage — call start_auto_stop_scheduler() once at app startup (e.g. in main.py)
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from smart_logger import get_logger
from session import session_manager
from config_mail import EmailConfig

logger = get_logger("auto_stop_scheduler")


# ── Load config ───────────────────────────────────────────────────────────────
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "app.properties")


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


# ── HTML mail builder — Detection Auto-Stop ───────────────────────────────────

def _build_html(stop_time_str: str, stopped_sessions: list, stop_dt: datetime) -> str:
    date_str     = stop_dt.strftime("%d %B %Y")
    weekday_str  = stop_dt.strftime("%A")
    time_display = stop_dt.strftime("%I:%M %p")

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
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;
                    box-shadow:0 4px 24px rgba(0,0,0,0.08);overflow:hidden;">
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
        <tr>
          <td style="padding:32px 40px;">
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
                      <td style="color:#78909C;font-size:14px;width:45%;">📅 Date</td>
                      <td style="color:#1A237E;font-size:14px;font-weight:600;">
                        {weekday_str}, {date_str}
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909C;font-size:14px;">⏰ Stop Time</td>
                      <td style="color:#1A237E;font-size:14px;font-weight:600;">
                        {time_display}
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909C;font-size:14px;">🔢 Sessions Stopped</td>
                      <td style="color:#4527A0;font-size:14px;font-weight:700;">
                        {len(stopped_sessions)}
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
            {sessions_block}
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#EDE7F6;border-radius:10px;
                          border-left:4px solid #7E57C2;">
              <tr>
                <td style="padding:14px 18px;">
                  <p style="margin:0;color:#4527A0;font-size:13px;line-height:1.5;">
                    ℹ️ To change the stop time, update <strong>AUTO_STOP_TIME</strong>
                    in <code>app.properties</code> and restart the service.
                    Raw video recording will continue until <strong>RAW_VIDEO_AUTO_STOP_TIME</strong>.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
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
    </td></tr>
  </table>
</body>
</html>"""


# ── HTML mail builder — Raw Video Auto-Stop ───────────────────────────────────

def _build_raw_stop_html(stop_dt: datetime, stopped_count: int) -> str:
    date_str     = stop_dt.strftime("%d %B %Y")
    weekday_str  = stop_dt.strftime("%A")
    time_display = stop_dt.strftime("%I:%M %p")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Raw Video Auto-Stop Alert</title>
</head>
<body style="margin:0;padding:0;background:#f0f4f8;
             font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f0f4f8;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;
                    box-shadow:0 4px 24px rgba(0,0,0,0.08);overflow:hidden;">
        <tr>
          <td style="background:linear-gradient(135deg,#E65100,#BF360C);
                      padding:28px 40px;text-align:center;">
            <div style="font-size:28px;margin-bottom:6px;">🎥</div>
            <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700;">
              Raw Video Recording Auto-Stopped
            </h1>
            <p style="margin:6px 0 0;color:#FFCCBC;font-size:13px;">
              Scheduled raw video shutdown — JL-CAM System
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 40px;">
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
                      <td style="color:#78909C;font-size:14px;width:45%;">📅 Date</td>
                      <td style="color:#1A237E;font-size:14px;font-weight:600;">
                        {weekday_str}, {date_str}
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909C;font-size:14px;">⏰ Stop Time</td>
                      <td style="color:#1A237E;font-size:14px;font-weight:600;">
                        {time_display}
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909C;font-size:14px;">🎥 Recordings Stopped</td>
                      <td style="color:#E65100;font-size:14px;font-weight:700;">
                        {stopped_count}
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#FBE9E7;border-radius:10px;
                          border-left:4px solid #FF5722;">
              <tr>
                <td style="padding:14px 18px;">
                  <p style="margin:0;color:#BF360C;font-size:13px;line-height:1.5;">
                    ℹ️ To change the raw video stop time, update
                    <strong>RAW_VIDEO_AUTO_STOP_TIME</strong>
                    in <code>app.properties</code> and restart the service.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
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
    </td></tr>
  </table>
</body>
</html>"""


# ── Mail sender — Detection Auto-Stop ────────────────────────────────────────

def _send_auto_stop_mail(stopped_sessions: list, stop_dt: datetime):
    try:
        time_display = stop_dt.strftime("%I:%M %p")
        date_str     = stop_dt.strftime("%d %B %Y")
        subject      = f"🛑 JL-CAM Detection Auto-Stopped at {time_display} — {date_str}"

        plain = (
            f"JL-CAM Auto-Stop Alert\n\n"
            f"Detection was automatically stopped at {time_display} on {date_str}.\n"
            f"Sessions stopped: {len(stopped_sessions)}\n"
            + ("\n".join(f"  - {s}" for s in stopped_sessions) if stopped_sessions
               else "  (no active sessions)")
            + "\n\nRaw video recording is still running until RAW_VIDEO_AUTO_STOP_TIME."
            + "\n\nThis is an automated notification from JL-CAM System."
        )

        msg = MIMEMultipart("alternative")
        msg["From"]    = EmailConfig.USERNAME
        msg["To"]      = ", ".join(EmailConfig.TO_EMAIL)
        msg["Subject"] = subject

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(
            _build_html(time_display, stopped_sessions, stop_dt), "html"
        ))

        with smtplib.SMTP(EmailConfig.SMTP_SERVER, EmailConfig.SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(EmailConfig.USERNAME, EmailConfig.PASSWORD)
            server.send_message(msg)

        logger.info(f"Auto-stop mail sent → {EmailConfig.TO_EMAIL}")

    except Exception:
        logger.exception("Auto-stop mail failed — sessions were still stopped")


# ── Mail sender — Raw Video Auto-Stop ────────────────────────────────────────

def _send_raw_stop_mail(stopped_count: int, stop_dt: datetime):
    try:
        time_display = stop_dt.strftime("%I:%M %p")
        date_str     = stop_dt.strftime("%d %B %Y")
        subject      = f"🎥 JL-CAM Raw Video Auto-Stopped at {time_display} — {date_str}"

        plain = (
            f"JL-CAM Raw Video Auto-Stop Alert\n\n"
            f"Raw video recording was automatically stopped at {time_display} on {date_str}.\n"
            f"Recordings stopped: {stopped_count}\n"
            + "\n\nThis is an automated notification from JL-CAM System."
        )

        msg = MIMEMultipart("alternative")
        msg["From"]    = EmailConfig.USERNAME
        msg["To"]      = ", ".join(EmailConfig.TO_EMAIL)
        msg["Subject"] = subject

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(
            _build_raw_stop_html(stop_dt, stopped_count), "html"
        ))

        with smtplib.SMTP(EmailConfig.SMTP_SERVER, EmailConfig.SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(EmailConfig.USERNAME, EmailConfig.PASSWORD)
            server.send_message(msg)

        logger.info(f"Raw video auto-stop mail sent → {EmailConfig.TO_EMAIL}")

    except Exception:
        logger.exception("Raw video auto-stop mail failed — recordings were still stopped")


# ── Detection scheduler loop ──────────────────────────────────────────────────

async def _scheduler_loop():
    while True:
        props = _load_props()

        enabled = props.get("AUTO_STOP_ENABLED", "true").lower() == "true"
        if not enabled:
            logger.info("AUTO_STOP_ENABLED=false — detection scheduler sleeping 60s")
            await asyncio.sleep(60)
            continue

        stop_time_str = props.get("AUTO_STOP_TIME", "18:00")

        try:
            stop_h, stop_m = map(int, stop_time_str.strip().split(":"))
        except ValueError:
            logger.error(
                f"Invalid AUTO_STOP_TIME='{stop_time_str}' — expected HH:MM. "
                f"Retrying in 60s."
            )
            await asyncio.sleep(60)
            continue

        now     = datetime.now()
        stop_dt = now.replace(hour=stop_h, minute=stop_m, second=0, microsecond=0)

        # If today's stop time already passed, schedule for tomorrow
        if now >= stop_dt:
            stop_dt += timedelta(days=1)

        wait_secs = (stop_dt - now).total_seconds()
        logger.info(
            f"Detection auto-stop scheduled at {stop_dt.strftime('%Y-%m-%d %H:%M')} "
            f"({wait_secs/60:.1f} min from now)"
        )

        await asyncio.sleep(wait_secs)

        # Re-read config at stop time (user may have changed it)
        props   = _load_props()
        enabled = props.get("AUTO_STOP_ENABLED", "true").lower() == "true"
        if not enabled:
            logger.info("AUTO_STOP_ENABLED turned off — skipping detection stop")
            continue

        # ── Stop ALL at AUTO_STOP_TIME: detection + segment recorder + processor + merge ──
        from segment_recorder import stop_segment_recorder
        from segment_processor import stop_segment_processor
        from segment_merger import merge_in_background

        active_ids = list(session_manager.sessions.keys())
        stopped    = []

        for sid in active_ids:
            if session_manager.is_active(sid):
                try:
                    tx_id = session_manager.sessions[sid].get("transaction_id")
                    session_manager.stop_session(sid)
                    stopped.append(sid)
                    logger.info(f"Auto-stopped detection session: {sid}")

                    if tx_id:
                        rec = None
                        try:
                            rec = stop_segment_recorder(tx_id)
                            logger.info(f"Segment recorder auto-stopped tx={tx_id[:8]}")
                        except Exception:
                            logger.exception(f"Failed to stop segment recorder tx={tx_id[:8]}")

                        proc = None
                        try:
                            logger.info(f"Draining segment processor tx={tx_id[:8]}")
                            proc = stop_segment_processor(tx_id, drain=True)
                            if proc:
                                logger.info(
                                    f"Segment processor auto-stopped tx={tx_id[:8]} "
                                    f"counts={proc.counts} inferred={proc.inferred_segs}"
                                )
                        except Exception:
                            logger.exception(f"Failed to stop segment processor tx={tx_id[:8]}")

                        try:
                            if rec and proc:
                                raw_segs = rec.get_segments()
                                inf_segs = proc.get_inferred_segments()
                                merge_in_background(
                                    transaction_id=tx_id,
                                    date_dir=rec.get_date_dir(),
                                    raw_segments=raw_segs,
                                    inferred_segments=inf_segs,
                                )
                                logger.info(
                                    f"Auto-stop merge started tx={tx_id[:8]} "
                                    f"raw={len(raw_segs)} inf={len(inf_segs)}"
                                )
                        except Exception:
                            logger.exception(f"Failed to start merge tx={tx_id[:8]}")

                except Exception:
                    logger.exception(f"Failed to auto-stop session: {sid}")

        logger.info(
            f"Full auto-stop complete at {stop_dt.strftime('%H:%M')} — "
            f"{len(stopped)} session(s) stopped."
        )

        _send_auto_stop_mail(stopped, stop_dt)
        # Sleep 90s before looping (avoids double-trigger at the same minute)
        await asyncio.sleep(90)


# ── Raw video scheduler loop — DISABLED (raw video now stops with detection at AUTO_STOP_TIME) ──

async def _raw_video_stop_scheduler_loop():
    while True:
        props = _load_props()

        enabled = props.get("AUTO_STOP_ENABLED", "true").lower() == "true"
        if not enabled:
            logger.info("AUTO_STOP_ENABLED=false — raw video scheduler sleeping 60s")
            await asyncio.sleep(60)
            continue

        raw_stop_time_str = props.get("RAW_VIDEO_AUTO_STOP_TIME", "19:30")

        try:
            stop_h, stop_m = map(int, raw_stop_time_str.strip().split(":"))
        except ValueError:
            logger.error(
                f"Invalid RAW_VIDEO_AUTO_STOP_TIME='{raw_stop_time_str}' — expected HH:MM. "
                f"Retrying in 60s."
            )
            await asyncio.sleep(60)
            continue

        now     = datetime.now()
        stop_dt = now.replace(hour=stop_h, minute=stop_m, second=0, microsecond=0)

        # If today's stop time already passed, schedule for tomorrow
        if now >= stop_dt:
            stop_dt += timedelta(days=1)

        wait_secs = (stop_dt - now).total_seconds()
        logger.info(
            f"Raw video auto-stop scheduled at {stop_dt.strftime('%Y-%m-%d %H:%M')} "
            f"({wait_secs/60:.1f} min from now)"
        )

        await asyncio.sleep(wait_secs)

        # Re-read config at stop time
        props   = _load_props()
        enabled = props.get("AUTO_STOP_ENABLED", "true").lower() == "true"
        if not enabled:
            logger.info("AUTO_STOP_ENABLED turned off — skipping raw video stop")
            continue

        # ── Stop all active raw recordings ────────────────────────────────────
        from raw_video import recorders, stop_raw_recording

        active_transactions = list(recorders.keys())
        stopped_count       = 0

        for tx_id in active_transactions:
            try:
                stop_raw_recording(tx_id)
                stopped_count += 1
                logger.info(f"Raw video auto-stopped for transaction: {tx_id}")
            except Exception:
                logger.exception(f"Failed to auto-stop raw recording: {tx_id}")

        logger.info(
            f"Raw video auto-stop complete at {stop_dt.strftime('%H:%M')} — "
            f"{stopped_count} recording(s) stopped"
        )

        _send_raw_stop_mail(stopped_count, stop_dt)

        # Sleep 90s before looping (avoids double-trigger at the same minute)
        await asyncio.sleep(90)


# ── Public entry point ────────────────────────────────────────────────────────

def start_auto_stop_scheduler():
    """
    Call once at startup (e.g. in main.py FastAPI startup handler).
    Spawns two background asyncio tasks — does not block.

    Task 1: _scheduler_loop()
        — stops detection sessions at AUTO_STOP_TIME (default 18:00)
        — raw video recording continues after this

    Task 2: _raw_video_stop_scheduler_loop()
        — stops raw video recordings at RAW_VIDEO_AUTO_STOP_TIME (default 19:30)
    """
    asyncio.create_task(_scheduler_loop())
    logger.info("Detection auto-stop scheduler started")

    asyncio.create_task(_raw_video_stop_scheduler_loop())
    logger.info("Raw video auto-stop scheduler started")