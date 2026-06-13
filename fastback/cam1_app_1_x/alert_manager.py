# alert_manager.py — Centralized Alert Manager
# ==============================================
# Sends email alerts for:
#   - CPU spike (>80%)
#   - GPU spike (>90%)
#   - Session crash
#   - System shutdown
#   - Disk low
#   - FFmpeg died
# All alerts go to unified log + email
# Non-blocking: runs in background thread
# ==============================================

import os
import smtplib
import threading
import queue
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from jl_logger import get_logger

logger = get_logger("ALERT")

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

ALERT_ON_CPU_SPIKE    = _props.get("ALERT_ON_CPU_SPIKE",    "true").lower() == "true"
ALERT_ON_GPU_SPIKE    = _props.get("ALERT_ON_GPU_SPIKE",    "true").lower() == "true"
ALERT_ON_CRASH        = _props.get("ALERT_ON_SESSION_CRASH","true").lower() == "true"
ALERT_ON_SHUTDOWN     = _props.get("ALERT_ON_SHUTDOWN",     "true").lower() == "true"
ALERT_ON_DISK_LOW     = _props.get("ALERT_ON_DISK_LOW",     "true").lower() == "true"
DISK_THRESHOLD_GB     = float(_props.get("ALERT_DISK_THRESHOLD_GB", "10"))

# ─────────────────────────────────────────────────
# Load mail config from .env
# ─────────────────────────────────────────────────
def _load_mail():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "config_mail",
            os.path.join(os.path.dirname(__file__), "config_mail.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.EmailConfig
    except Exception as e:
        logger.error(f"Mail config load failed: {e}", exc_info=True)
        return None

# ─────────────────────────────────────────────────
# Alert severity colors
# ─────────────────────────────────────────────────
_SEVERITY_COLORS = {
    "critical": "#B71C1C",
    "high":     "#E53935",
    "warning":  "#F57C00",
    "info":     "#1565C0",
}

_SEVERITY_EMOJI = {
    "critical": "🔴",
    "high":     "🟠",
    "warning":  "🟡",
    "info":     "🔵",
}

# ─────────────────────────────────────────────────
# HTML builder
# ─────────────────────────────────────────────────
def _build_alert_html(
    title:       str,
    severity:    str,
    details:     dict,
    description: str = "",
) -> str:
    color   = _SEVERITY_COLORS.get(severity, "#1565C0")
    emoji   = _SEVERITY_EMOJI.get(severity, "⚠️")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = ""
    for k, v in details.items():
        rows += f"""<tr>
            <td style="padding:8px 16px;color:#78909C;font-size:14px;width:45%;">{k}</td>
            <td style="padding:8px 16px;color:#1A237E;font-size:14px;font-weight:600;">{v}</td>
        </tr>"""

    desc_block = ""
    if description:
        desc_block = f"""
        <div style="background:#FFF8E1;border-radius:10px;border-left:4px solid #FFC107;
                    padding:14px 18px;margin-bottom:24px;">
          <p style="margin:0;color:#5D4037;font-size:14px;font-family:monospace;
                    white-space:pre-wrap;">{description}</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4f8;padding:40px 0;">
  <tr><td align="center">
  <table width="580" cellpadding="0" cellspacing="0"
         style="background:#fff;border-radius:16px;
                box-shadow:0 4px 24px rgba(0,0,0,0.08);overflow:hidden;">

    <tr><td style="background:linear-gradient(135deg,{color},{color}CC);
                    padding:28px 40px;text-align:center;">
      <div style="font-size:32px;margin-bottom:6px;">{emoji}</div>
      <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700;">{title}</h1>
      <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">
        JL-CAM Harmony System — {now_str}
      </p>
    </td></tr>

    <tr><td style="padding:32px 40px;">
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#F8FAFB;border-radius:12px;
                    border:1px solid #E3EAF0;margin-bottom:24px;">
        {rows}
      </table>
      {desc_block}
      <div style="background:#EDE7F6;border-radius:10px;border-left:4px solid #7E57C2;
                  padding:12px 18px;">
        <p style="margin:0;color:#4527A0;font-size:12px;">
          ℹ️ Check unified log at
          <code>/var/log/smartcounter/jlcam_{datetime.now().strftime('%Y-%m-%d')}.log</code>
          for full details.
        </p>
      </div>
    </td></tr>

    <tr><td style="background:#F5F7FA;padding:16px 40px;
                    border-top:1px solid #ECEFF1;text-align:center;">
      <p style="margin:0;color:#90A4AE;font-size:12px;">
        JL-CAM Harmony System — Automated Alert<br>
        Please do not reply to this email.
      </p>
    </td></tr>
  </table>
  </td></tr>
</table>
</body></html>"""

# ─────────────────────────────────────────────────
# Non-blocking email queue
# ─────────────────────────────────────────────────
_alert_queue: queue.Queue = queue.Queue(maxsize=50)
_worker_thread: Optional[threading.Thread] = None

def _send_email(subject: str, html: str, plain: str) -> bool:
    """Send email synchronously. Returns True on success."""
    try:
        mail = _load_mail()
        if not mail or not mail.USERNAME or not mail.PASSWORD:
            logger.warning("Alert email skipped — mail config incomplete")
            return False

        # Use ALERT_TO_EMAIL if set, otherwise fall back to TO_EMAIL
        import os
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
        alert_to = os.getenv("ALERT_TO_EMAIL", "")
        recipients = [e.strip() for e in alert_to.split(",") if e.strip()]                      if alert_to else mail.TO_EMAIL

        msg = MIMEMultipart("alternative")
        msg["From"]    = mail.USERNAME
        msg["To"]      = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(mail.SMTP_SERVER, mail.SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(mail.USERNAME, mail.PASSWORD)
            server.send_message(msg)

        logger.info(f"Alert email sent → {mail.TO_EMAIL} subject={subject[:50]}")
        return True

    except Exception as e:
        logger.error(f"Alert email failed: {e}", exc_info=True)
        return False

def _worker():
    """Background thread — processes alert queue."""
    logger.info("Alert email worker started")
    while True:
        try:
            item = _alert_queue.get(timeout=5)
            if item is None:
                break
            subject, html, plain = item
            _send_email(subject, html, plain)
            _alert_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Alert worker error: {e}", exc_info=True)

def _start_worker():
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_thread = threading.Thread(
        target=_worker, name="alert_worker", daemon=True
    )
    _worker_thread.start()

def _queue_alert(subject: str, html: str, plain: str):
    """Queue alert for async sending."""
    _start_worker()
    try:
        _alert_queue.put_nowait((subject, html, plain))
    except queue.Full:
        logger.warning("Alert queue full — dropping alert")

# ─────────────────────────────────────────────────
# Public alert functions
# ─────────────────────────────────────────────────

def alert_cpu_spike(cpu_pct: float):
    """Alert when CPU goes above threshold."""
    if not ALERT_ON_CPU_SPIKE:
        return
    logger.warning(f"ALERT: CPU spike {cpu_pct:.1f}%")
    subject = f"🟠 JL-CAM CPU Spike Alert — {cpu_pct:.1f}% — {datetime.now().strftime('%H:%M:%S')}"
    details = {
        "⚡ CPU Usage":     f"{cpu_pct:.1f}%",
        "📊 Threshold":     f"{_props.get('INFERENCE_CPU_THRESHOLD', '80')}%",
        "⏰ Time":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "🎯 Action":        "YOLOX inference paused — will resume when CPU normalizes",
    }
    html  = _build_alert_html("CPU Spike Detected", "high", details,
                               "YOLOX inference has been paused to protect system stability.\n"
                               "It will resume automatically when CPU drops below threshold.")
    plain = f"JL-CAM CPU Spike Alert\nCPU: {cpu_pct:.1f}%\nYOLOX inference paused."
    _queue_alert(subject, html, plain)

def alert_cpu_normal(cpu_pct: float):
    """Alert when CPU returns to normal."""
    if not ALERT_ON_CPU_SPIKE:
        return
    logger.info(f"ALERT: CPU normalized {cpu_pct:.1f}%")
    subject = f"✅ JL-CAM CPU Normalized — {cpu_pct:.1f}% — {datetime.now().strftime('%H:%M:%S')}"
    details = {
        "✅ CPU Usage":   f"{cpu_pct:.1f}%",
        "⏰ Time":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "🎯 Action":      "YOLOX inference resumed",
    }
    html  = _build_alert_html("CPU Normalized — Inference Resumed", "info", details)
    plain = f"JL-CAM CPU Normal\nCPU: {cpu_pct:.1f}%\nYOLOX inference resumed."
    _queue_alert(subject, html, plain)

def alert_session_crash(
    session_id:     str,
    transaction_id: str,
    duration_secs:  float,
    error:          str = "",
    restart_in:     int = 30,
):
    """Alert when a session crashes unexpectedly."""
    if not ALERT_ON_CRASH:
        return
    logger.error(
        f"ALERT: Session crash → session={session_id[:8]} "
        f"duration={duration_secs:.0f}s error={error}"
    )
    subject = (
        f"🔴 JL-CAM Session Crashed — "
        f"{datetime.now().strftime('%H:%M:%S')} — "
        f"Restarting in {restart_in}s"
    )
    details = {
        "🆔 Session ID":      session_id[:8] + "...",
        "📋 Transaction ID":  transaction_id[:8] + "...",
        "⏱ Duration":         f"{duration_secs:.0f}s ({duration_secs/60:.1f} min)",
        "❌ Error":            error or "NO_FRAMES / connection dropped",
        "⏰ Crashed At":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "🔄 Auto-Restart In": f"{restart_in} seconds",
    }
    html  = _build_alert_html(
        "Detection Session Crashed", "high", details,
        f"Error details:\n{error}" if error else ""
    )
    plain = (
        f"JL-CAM Session Crashed\n"
        f"Session: {session_id[:8]}\n"
        f"Duration: {duration_secs:.0f}s\n"
        f"Error: {error or 'NO_FRAMES'}\n"
        f"Restarting in {restart_in}s"
    )
    _queue_alert(subject, html, plain)

def alert_shutdown(reason: str = "scheduled", counts: dict = None):
    """Alert when system shuts down."""
    if not ALERT_ON_SHUTDOWN:
        return
    logger.info(f"ALERT: System shutdown → reason={reason}")
    subject = (
        f"🛑 JL-CAM System Shutdown — "
        f"{datetime.now().strftime('%H:%M:%S')} — "
        f"{reason}"
    )
    details = {
        "🛑 Reason":     reason,
        "⏰ Time":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if counts:
        details["📦 Box Count"]    = counts.get("box",     0)
        details["🎁 Bale Count"]   = counts.get("bale",    0)
        details["🛒 Trolley Count"]= counts.get("trolley", 0)
    html  = _build_alert_html("System Shutdown", "warning", details)
    plain = f"JL-CAM Shutdown\nReason: {reason}\nTime: {datetime.now().strftime('%H:%M:%S')}"
    # Send synchronously — system is shutting down
    _send_email(subject, html, plain)

def alert_disk_low(free_gb: float):
    """Alert when disk space is critically low."""
    if not ALERT_ON_DISK_LOW:
        return
    logger.warning(f"ALERT: Disk low {free_gb:.1f}GB free")
    subject = f"💿 JL-CAM Disk Space Low — {free_gb:.1f}GB free"
    details = {
        "💿 Free Space":   f"{free_gb:.1f} GB",
        "⚠️ Threshold":    f"{DISK_THRESHOLD_GB} GB",
        "⏰ Time":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "🎯 Action":       "Run housekeeping or delete old raw videos",
    }
    html  = _build_alert_html("Disk Space Low", "critical", details)
    plain = f"JL-CAM Disk Low\nFree: {free_gb:.1f}GB\nAction: Clean up old videos."
    _queue_alert(subject, html, plain)

def alert_ffmpeg_died(cam: str):
    """Alert when FFmpeg process dies."""
    logger.error(f"ALERT: FFmpeg died for {cam}")
    subject = f"🔴 JL-CAM FFmpeg Died — {cam} — {datetime.now().strftime('%H:%M:%S')}"
    details = {
        "📷 Camera":  cam,
        "❌ Status":  "FFmpeg process not found",
        "⏰ Time":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "🎯 Action":  "System will attempt to restart FFmpeg on next boot",
    }
    html  = _build_alert_html("FFmpeg Process Died", "critical", details)
    plain = f"JL-CAM FFmpeg Died\nCam: {cam}\nAction: Check system logs."
    _queue_alert(subject, html, plain)

