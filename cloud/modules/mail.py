# modules/mail.py

import smtplib
from email.mime.text import MIMEText
from utils_config_loader import load_properties
from logger import get_logger
from threading import Lock

logger = get_logger("mail")

# Load config
CONFIG = load_properties("config.properties")

MAIL_USER = CONFIG.get("MAIL_USER")            # your zoho email
MAIL_PASS = CONFIG.get("MAIL_PASS")            # your zoho app password
SMTP_HOST = CONFIG.get("SMTP_HOST", "smtp.zoho.in")
SMTP_PORT = int(CONFIG.get("SMTP_PORT", "587"))

# GLOBAL SMTP CONNECTION (persistent)
smtp_server = None
smtp_lock = Lock()


def create_smtp_connection():
    """
    Creates an SMTP connection (Zoho).
    """
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
        server.starttls()
        server.login(MAIL_USER, MAIL_PASS)
        logger.info("SMTP connection established successfully.")
        return server
    except Exception as e:
        logger.error(f"SMTP connection failed: {e}", exc_info=True)
        return None


def get_smtp_connection():
    """
    Provides a global reusable SMTP connection.
    If connection is closed or None → reconnect automatically.
    """
    global smtp_server

    # If first time or connection dropped → reconnect
    if smtp_server is None:
        smtp_server = create_smtp_connection()
        return smtp_server

    # Test connection
    try:
        smtp_server.noop()  # ping server
        return smtp_server
    except Exception:
        logger.warning("SMTP server died, reconnecting...")
        smtp_server = create_smtp_connection()
        return smtp_server


def send_mail(server: smtplib.SMTP, to_email: str, subject: str, user_data: dict):
    """
    Thread-safe mail sending using a shared SMTP connection.
    """

    name = user_data.get("name", "Unknown")
    role = user_data.get("role", "Unknown")
    otp = user_data.get("otp", "----")

    body = f"""
Dear Sir/Madam,

A new user registration request has been submitted and requires your review.

Applicant Details:
• Name : {name}
• Role : {role}

Verification OTP:
🔐 {otp}

Regards,
"""

    msg = MIMEText(body)
    msg["From"] = MAIL_USER
    msg["To"] = to_email
    msg["Subject"] = subject

    try:
        # Thread-safe write to SMTP socket
        with smtp_lock:
            server.send_message(msg)

        logger.info(f"Mail delivered → {to_email}")

    except Exception as e:
        logger.error(f"Mail delivery failed → {to_email}: {e}", exc_info=True)

        # Attempt reconnect and retry ONCE
        try:
            new_server = create_smtp_connection()
            if new_server:
                with smtp_lock:
                    new_server.send_message(msg)
                logger.info(f"Mail delivered after reconnect → {to_email}")
        except Exception as e2:
            logger.error(f"Mail retry failed → {to_email}: {e2}", exc_info=True)


def close_smtp_connection():
    """
    Safely closes the global SMTP connection.
    """
    global smtp_server
    try:
        if smtp_server:
            smtp_server.quit()
            logger.info("Global SMTP connection closed")
    except Exception:
        pass
    smtp_server = None
