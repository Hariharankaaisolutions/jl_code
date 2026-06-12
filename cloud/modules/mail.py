# modules/mail.py

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from utils_config_loader import load_properties
from logger import get_logger
from threading import Lock

logger = get_logger("mail")

CONFIG    = load_properties("config.properties")
MAIL_USER = CONFIG.get("MAIL_USER")
MAIL_PASS = CONFIG.get("MAIL_PASS")
SMTP_HOST = CONFIG.get("SMTP_HOST", "smtp.zoho.in")
SMTP_PORT = int(CONFIG.get("SMTP_PORT", "587"))

smtp_server = None
smtp_lock   = Lock()


# ─────────────────────────────────────────────────────────────
# SMTP helpers  (unchanged behaviour)
# ─────────────────────────────────────────────────────────────

def create_smtp_connection():
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
    global smtp_server

    if smtp_server is None:
        smtp_server = create_smtp_connection()
        return smtp_server

    try:
        smtp_server.noop()
        return smtp_server
    except Exception:
        logger.warning("SMTP server died, reconnecting...")
        smtp_server = create_smtp_connection()
        return smtp_server


def close_smtp_connection():
    global smtp_server
    try:
        if smtp_server:
            smtp_server.quit()
            logger.info("Global SMTP connection closed")
    except Exception:
        pass
    smtp_server = None


# ─────────────────────────────────────────────────────────────
# HTML builder — OTP registration alert
# ─────────────────────────────────────────────────────────────

def _build_html(name: str, role: str, otp: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>New User Registration OTP</title>
</head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:'Segoe UI',Arial,sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4f8;padding:40px 0;">
    <tr>
      <td align="center">

        <!-- Card -->
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:16px;
                      box-shadow:0 4px 24px rgba(0,0,0,0.08);overflow:hidden;">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#1565C0,#0D47A1);
                        padding:32px 40px;text-align:center;">
              <div style="font-size:28px;margin-bottom:6px;">🔐</div>
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;
                          letter-spacing:0.5px;">New Registration Request</h1>
              <p style="margin:6px 0 0;color:#90CAF9;font-size:13px;">
                Approval &amp; OTP Required
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:36px 40px;">

              <p style="margin:0 0 24px;color:#37474F;font-size:15px;line-height:1.6;">
                Dear Sir / Madam,<br><br>
                A new user has submitted a registration request and is awaiting your approval.
                Please review the details below and share the OTP with the applicant if approved.
              </p>

              <!-- Applicant details -->
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#F8FAFB;border-radius:12px;
                            border:1px solid #E3EAF0;margin-bottom:28px;">
                <tr>
                  <td style="padding:20px 24px;">
                    <p style="margin:0 0 6px;font-size:11px;font-weight:700;
                               color:#90A4AE;letter-spacing:1px;text-transform:uppercase;">
                      Applicant Details
                    </p>

                    <table width="100%" cellpadding="6" cellspacing="0">
                      <tr>
                        <td width="40%" style="color:#78909C;font-size:14px;">👤 Name</td>
                        <td style="color:#1A237E;font-size:14px;font-weight:600;">{name}</td>
                      </tr>
                      <tr>
                        <td style="color:#78909C;font-size:14px;">🏷️ Role</td>
                        <td style="color:#1A237E;font-size:14px;font-weight:600;">{role}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- OTP box -->
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:linear-gradient(135deg,#E3F2FD,#BBDEFB);
                            border-radius:12px;border:1px solid #90CAF9;
                            margin-bottom:28px;">
                <tr>
                  <td style="padding:24px;text-align:center;">
                    <p style="margin:0 0 10px;font-size:12px;font-weight:700;
                               color:#1565C0;letter-spacing:1.5px;text-transform:uppercase;">
                      Verification OTP
                    </p>
                    <div style="font-size:42px;font-weight:800;letter-spacing:12px;
                                color:#0D47A1;font-family:'Courier New',monospace;">
                      {otp}
                    </div>
                    <p style="margin:10px 0 0;font-size:12px;color:#1976D2;">
                      Share this OTP only if you approve this registration.
                    </p>
                  </td>
                </tr>
              </table>

              <!-- Warning note -->
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#FFF8E1;border-radius:10px;
                            border-left:4px solid #FFC107;margin-bottom:8px;">
                <tr>
                  <td style="padding:14px 18px;">
                    <p style="margin:0;color:#795548;font-size:13px;line-height:1.5;">
                      ⚠️ <strong>Do not share this OTP</strong> if you do not recognise
                      this request or did not authorise this registration.
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#F5F7FA;padding:20px 40px;
                        border-top:1px solid #ECEFF1;text-align:center;">
              <p style="margin:0;color:#90A4AE;font-size:12px;line-height:1.6;">
                This is an automated notification from <strong>JL-CAM System</strong>.<br>
                Please do not reply to this email.
              </p>
            </td>
          </tr>

        </table>
        <!-- /Card -->

      </td>
    </tr>
  </table>

</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# Public send_mail — same signature as before
# ─────────────────────────────────────────────────────────────

def send_mail(server: smtplib.SMTP, to_email: str, subject: str, user_data: dict):
    """
    Thread-safe HTML mail sending using a shared SMTP connection.
    Signature unchanged — drop-in replacement for the old send_mail.
    """
    name = user_data.get("name", "Unknown")
    role = user_data.get("role", "Unknown")
    otp  = user_data.get("otp",  "----")

    # Multipart so clients that can't render HTML get plain-text fallback
    msg = MIMEMultipart("alternative")
    msg["From"]    = MAIL_USER
    msg["To"]      = to_email
    msg["Subject"] = subject

    # Plain-text fallback
    plain = (
        f"Dear Sir/Madam,\n\n"
        f"A new user registration request has been submitted.\n\n"
        f"Applicant Details:\n"
        f"  Name : {name}\n"
        f"  Role : {role}\n\n"
        f"Verification OTP: {otp}\n\n"
        f"Share this OTP only if you approve the registration.\n\n"
        f"Regards,\nJL-CAM System"
    )

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_build_html(name, role, otp), "html"))

    try:
        with smtp_lock:
            server.send_message(msg)
        logger.info(f"Mail delivered → {to_email}")

    except Exception as e:
        logger.error(f"Mail delivery failed → {to_email}: {e}", exc_info=True)

        # Retry once with a fresh connection
        try:
            new_server = create_smtp_connection()
            if new_server:
                with smtp_lock:
                    new_server.send_message(msg)
                logger.info(f"Mail delivered after reconnect → {to_email}")
        except Exception as e2:
            logger.error(f"Mail retry failed → {to_email}: {e2}", exc_info=True)