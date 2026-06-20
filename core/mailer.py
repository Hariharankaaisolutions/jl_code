"""
core/mailer.py — Email Sender
==============================
Handles all email sending for JL-CAM system.
Reads SMTP config from master.properties.
Three recipient groups: ADMIN, ALERT, EDIT_ALERT.
Max 100 lines. One responsibility: send emails.
"""

import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

from core.config import get, getint, getlist
from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("MAIL")

# ── Config ─────────────────────────────────────────────────────
SMTP_HOST    = get("SMTP_HOST",     "smtp.zoho.in")
SMTP_PORT    = getint("SMTP_PORT",  587)
SMTP_USER    = get("SMTP_USERNAME", "")
SMTP_PASS    = get("SMTP_PASSWORD", "")
ADMIN_EMAIL  = getlist("ADMIN_EMAIL")
ALERT_EMAIL  = getlist("ALERT_EMAIL")
EDIT_EMAIL   = getlist("EDIT_ALERT_EMAIL")

# ── Lock for thread safety ─────────────────────────────────────
_lock = threading.Lock()


def _send(to: list[str], subject: str, html: str, plain: str = "") -> bool:
    """Core send function. Returns True on success."""
    if not to:
        logger.warning(LOG("MAIL.004.ERROR",
            subject=subject, error="No recipients"))
        return False
    try:
        msg              = MIMEMultipart("alternative")
        msg["From"]      = SMTP_USER
        msg["To"]        = ", ".join(to)
        msg["Subject"]   = subject
        if plain:
            msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))

        with _lock:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as srv:
                srv.starttls()
                srv.login(SMTP_USER, SMTP_PASS)
                srv.sendmail(SMTP_USER, to, msg.as_string())

        logger.info(LOG("MAIL.003.INFO", subject=subject, to=to))
        return True
    except Exception as e:
        logger.error(LOG("MAIL.004.ERROR", subject=subject, error=e))
        return False


def _send_async(to: list[str], subject: str, html: str, plain: str = "") -> None:
    """Send email in background thread — non-blocking."""
    t = threading.Thread(
        target=_send, args=(to, subject, html, plain), daemon=True
    )
    t.start()


def send_admin(subject: str, html: str, plain: str = "") -> None:
    """Send to ADMIN_EMAIL (boot, stop, session complete, housekeeping)."""
    _send_async(ADMIN_EMAIL, subject, html, plain)


def send_alert(subject: str, html: str, plain: str = "") -> None:
    """Send to ALERT_EMAIL (crash, CPU, GPU, disk, RAM alerts)."""
    _send_async(ALERT_EMAIL, subject, html, plain)


def send_edit_alert(subject: str, html: str, plain: str = "") -> None:
    """Send to EDIT_ALERT_EMAIL (dashboard edits)."""
    _send_async(EDIT_EMAIL, subject, html, plain)


def send_metric_alert(metric: str, value, threshold, unit: str = "") -> None:
    """Send metric threshold alert to ALERT_EMAIL."""
    subject = f"⚠️ JL-CAM Alert — {metric}: {value}{unit} (threshold: {threshold}{unit})"
    now     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html    = f"""
    <div style="font-family:Arial;padding:20px;">
      <h2 style="color:#E65100;">⚠️ JL-CAM System Alert</h2>
      <table style="border-collapse:collapse;width:100%;">
        <tr><td style="padding:8px;color:#666;">Metric</td>
            <td style="padding:8px;font-weight:bold;">{metric}</td></tr>
        <tr style="background:#FFF8E1;">
            <td style="padding:8px;color:#666;">Value</td>
            <td style="padding:8px;color:#E65100;font-weight:bold;">{value}{unit}</td></tr>
        <tr><td style="padding:8px;color:#666;">Threshold</td>
            <td style="padding:8px;">{threshold}{unit}</td></tr>
        <tr style="background:#FFF8E1;">
            <td style="padding:8px;color:#666;">Time</td>
            <td style="padding:8px;">{now} IST</td></tr>
        <tr><td style="padding:8px;color:#666;">Machine</td>
            <td style="padding:8px;">JL-Z440</td></tr>
      </table>
    </div>"""
    plain = (f"JL-CAM Alert\nMetric: {metric}\n"
             f"Value: {value}{unit}\nThreshold: {threshold}{unit}\nTime: {now}")
    logger.info(LOG("MAIL.011.INFO", metric=metric, value=value))
    _send_async(ALERT_EMAIL, subject, html, plain)
