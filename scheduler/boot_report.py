"""
scheduler/boot_report.py — Boot Report Email
==============================================
Sends boot report email with yesterday's counts.
Called once at startup after AUTO_START_DELAY.
Max 60 lines. One responsibility: send boot report.
"""

from datetime import datetime

from core.config import getbool, get
from core.logger import get_logger
from core.log_codes import get as LOG
from core.mailer import send_admin
from core.db_daily_counts import get_yesterday_totals

logger = get_logger("BOOT")


def send(cam: str = "cam_1") -> None:
    if not getbool("EMAIL_BOOT_REPORT", True):
        return
    try:
        logger.info(LOG("BOOT.001.INFO"))
        yesterday = get_yesterday_totals(cam)
        now       = datetime.now()

        subject = (f"🚀 JL-CAM Boot Report — "
                   f"{now.strftime('%d %b %Y %I:%M %p')}")

        html = f"""
        <div style="font-family:Arial;padding:20px;">
          <h2 style="color:#1565C0;">🚀 JL-CAM System Started</h2>
          <table style="border-collapse:collapse;width:100%;">
            <tr><td style="padding:8px;color:#666;">📅 Boot Time</td>
                <td style="padding:8px;font-weight:bold;">
                    {now.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
            <tr style="background:#E3F2FD;">
                <td style="padding:8px;color:#666;">📷 Camera</td>
                <td style="padding:8px;">{cam}</td></tr>
            <tr><td colspan="2" style="padding:12px 8px 4px;
                    font-weight:bold;color:#1565C0;">
                    Yesterday's Counts ({yesterday['date']})</td></tr>
            <tr style="background:#E3F2FD;">
                <td style="padding:8px;color:#666;">📦 Box</td>
                <td style="padding:8px;font-weight:bold;">
                    {yesterday['box']}</td></tr>
            <tr><td style="padding:8px;color:#666;">🧱 Bale</td>
                <td style="padding:8px;font-weight:bold;">
                    {yesterday['bale']}</td></tr>
            <tr style="background:#E3F2FD;">
                <td style="padding:8px;color:#666;">🛒 Trolley</td>
                <td style="padding:8px;font-weight:bold;">
                    {yesterday['trolley']}</td></tr>
            <tr><td style="padding:8px;color:#666;">📊 Sessions</td>
                <td style="padding:8px;font-weight:bold;">
                    {yesterday['session_count']}</td></tr>
          </table>
        </div>"""

        plain = (f"JL-CAM Boot Report\n"
                 f"Boot Time: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                 f"Yesterday ({yesterday['date']}): "
                 f"box={yesterday['box']} bale={yesterday['bale']} "
                 f"trolley={yesterday['trolley']}")

        send_admin(subject, html, plain)
        logger.info(LOG("BOOT.002.INFO", to="ADMIN_EMAIL"))

    except Exception as e:
        logger.error(LOG("BOOT.003.ERROR", error=e))
