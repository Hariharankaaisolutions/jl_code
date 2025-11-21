# mail.py — SmartLogger Edition
# =================================================

from smart_logger import get_logger
logger = get_logger(__name__)

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config_mail import EmailConfig
from message_loader import Messages


def send_email(subject, body):
    """
    Send email using SMTP with full SmartLogger instrumentation.
    Logs are taken from messages.properties via Messages.get().
    """

    # Preparing to send
    logger.info(
        Messages.get("MAIL.SEND.001.INFO", subject=subject)
    )

    try:
        # ---------------------------------------------------------
        # Construct MIME message
        # ---------------------------------------------------------
        logger.debug(
            Messages.get(
                "MAIL.SEND.002.DEBUG",
                from_email=EmailConfig.FROM_EMAIL,
                to_email=EmailConfig.TO_EMAIL,
                subject=subject,
            )
        )

        msg = MIMEMultipart()
        msg["From"] = EmailConfig.FROM_EMAIL
        msg["To"] = ", ".join(EmailConfig.TO_EMAIL)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        logger.debug(Messages.get("MAIL.SEND.003.DEBUG"))

        # ---------------------------------------------------------
        # Connect to SMTP
        # ---------------------------------------------------------
        logger.debug(
            Messages.get(
                "MAIL.SEND.004.DEBUG",
                smtp_server=EmailConfig.SMTP_SERVER,
                smtp_port=EmailConfig.SMTP_PORT,
            )
        )

        with smtplib.SMTP(
            EmailConfig.SMTP_SERVER,
            EmailConfig.SMTP_PORT
        ) as server:

            logger.debug(Messages.get("MAIL.SEND.005.DEBUG"))
            server.starttls()

            logger.debug(Messages.get("MAIL.SEND.006.DEBUG"))

            # ---------------------------------------------------------
            # Login
            # ---------------------------------------------------------
            logger.debug(
                Messages.get(
                    "MAIL.SEND.007.DEBUG",
                    username=EmailConfig.USERNAME,
                )
            )
            server.login(
                EmailConfig.USERNAME,
                EmailConfig.PASSWORD
            )

            logger.debug(Messages.get("MAIL.SEND.008.DEBUG"))

            # ---------------------------------------------------------
            # Send email
            # ---------------------------------------------------------
            logger.debug(Messages.get("MAIL.SEND.009.DEBUG"))
            server.sendmail(
                EmailConfig.FROM_EMAIL,
                EmailConfig.TO_EMAIL,
                msg.as_string()
            )

        logger.info(
            Messages.get("MAIL.SEND.010.INFO", subject=subject)
        )

    except Exception:
        logger.exception(
            Messages.get("MAIL.SEND.011.ERROR", subject=subject)
        )
