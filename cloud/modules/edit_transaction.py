# modules/edit_transaction.py
# ─────────────────────────────────────────────────────────────────────────────
# REST endpoint:  PUT /api/transactions/{transaction_id}
#
# On every successful edit:
#   1. Reads OLD values from DB before updating
#   2. Writes NEW values to DB
#   3. Sends alert mail to all addresses in EDIT_ALERT_MAIL (config.properties)
#      showing who edited, old → new counts, vehicle, start/end time
#
# Reuses the existing modules/mail.py SMTP connection (same as registration).
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import psycopg2

from utils_config_loader import load_properties
from logger import get_logger
from modules.mail import get_smtp_connection, smtp_lock

router = APIRouter(tags=["Edit Transaction"])
logger = get_logger("edit_transaction")

CONFIG = load_properties("config.properties")

MAIL_USER = CONFIG.get("MAIL_USER", "")

# ── Recipients — comma-separated in config.properties ─────────
_raw = CONFIG.get("EDIT_ALERT_MAIL", "")
EDIT_ALERT_RECIPIENTS: list[str] = [
    m.strip() for m in _raw.split(",") if m.strip()
]

DB_CONFIG = {
    "dbname":   CONFIG.get("DB_NAME",     "jlmill"),
    "user":     CONFIG.get("DB_USER",     "kaai"),
    "password": CONFIG.get("DB_PASSWORD", "yourpassword"),
    "host":     CONFIG.get("DB_HOST",     "localhost"),
    "port":     CONFIG.get("DB_PORT",     "5432"),
}


# ─────────────────────────────────────────────────────────────
# DB helper
# ─────────────────────────────────────────────────────────────
def get_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        logger.error(f"DB connection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database connection failed")


# ─────────────────────────────────────────────────────────────
# HTML builder — edit alert
# ─────────────────────────────────────────────────────────────

def _build_edit_html(
    transaction_id: str,
    edited_by:      str,
    date:           str,
    start_time:     str,
    end_time:       str,
    old:            dict,
    new:            dict,
) -> str:

    end_display = end_time if end_time and end_time.lower() != "none" else "Still running"

    # Build diff rows
    fields = [
        ("🚗 Vehicle Number", old["vehicle"],  new["vehicle"]),
        ("📦 Box Count",      old["box"],      new["box"]),
        ("🧱 Bale Count",     old["bale"],     new["bale"]),
        ("🛍️ Bag Count",     old["bag"],      new["bag"]),
        ("🛒 Trolley Count",  old["trolley"],  new["trolley"]),
    ]

    rows_html = ""
    for label, old_val, new_val in fields:
        changed  = str(old_val) != str(new_val)
        bg       = "#FFF8E1" if changed else "#FAFAFA"
        badge    = (
            '<span style="background:#FF8F00;color:#fff;font-size:10px;'
            'font-weight:700;padding:2px 8px;border-radius:20px;'
            'margin-left:8px;vertical-align:middle;">CHANGED</span>'
            if changed else ""
        )
        old_color = "#E53935" if changed else "#546E7A"
        new_color = "#2E7D32" if changed else "#546E7A"

        rows_html += f"""
        <tr style="background:{bg};">
          <td style="padding:12px 16px;color:#546E7A;font-size:14px;
                     border-bottom:1px solid #ECEFF1;">{label}{badge}</td>
          <td style="padding:12px 16px;text-align:center;font-size:14px;
                     font-weight:600;color:{old_color};
                     border-bottom:1px solid #ECEFF1;">{old_val}</td>
          <td style="padding:12px 16px;text-align:center;font-size:18px;
                     color:#90A4AE;border-bottom:1px solid #ECEFF1;">→</td>
          <td style="padding:12px 16px;text-align:center;font-size:14px;
                     font-weight:700;color:{new_color};
                     border-bottom:1px solid #ECEFF1;">{new_val}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Transaction Edit Alert</title>
</head>
<body style="margin:0;padding:0;background:#f0f4f8;
             font-family:'Segoe UI',Arial,sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f0f4f8;padding:40px 0;">
    <tr><td align="center">

      <!-- Card -->
      <table width="580" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;
                    box-shadow:0 4px 24px rgba(0,0,0,0.08);overflow:hidden;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#E65100,#BF360C);
                      padding:28px 40px;text-align:center;">
            <div style="font-size:26px;margin-bottom:6px;">✏️</div>
            <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700;">
              Transaction Edited
            </h1>
            <p style="margin:6px 0 0;color:#FFCCBC;font-size:13px;">
              JL-CAM Edit Alert
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px 40px;">

            <!-- Meta info -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#F8FAFB;border-radius:12px;
                          border:1px solid #E3EAF0;margin-bottom:28px;">
              <tr>
                <td style="padding:20px 24px;">
                  <p style="margin:0 0 12px;font-size:11px;font-weight:700;
                             color:#90A4AE;letter-spacing:1px;
                             text-transform:uppercase;">Transaction Info</p>
                  <table width="100%" cellpadding="6" cellspacing="0">
                    <tr>
                      <td style="color:#78909C;font-size:13px;width:45%;">
                        🔖 Transaction ID
                      </td>
                      <td style="color:#1A237E;font-size:13px;font-weight:700;
                                 font-family:'Courier New',monospace;">
                        {transaction_id}
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909C;font-size:13px;">📅 Date</td>
                      <td style="color:#1A237E;font-size:13px;font-weight:600;">
                        {date}
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909C;font-size:13px;">⏰ Start Time</td>
                      <td style="color:#1A237E;font-size:13px;font-weight:600;">
                        {start_time}
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909C;font-size:13px;">🏁 End Time</td>
                      <td style="color:#1A237E;font-size:13px;font-weight:600;">
                        {end_display}
                      </td>
                    </tr>
                    <tr>
                      <td style="color:#78909C;font-size:13px;">👤 Edited By</td>
                      <td style="color:#E65100;font-size:13px;font-weight:700;">
                        {edited_by}
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <!-- Changes table -->
            <p style="margin:0 0 10px;font-size:11px;font-weight:700;
                       color:#90A4AE;letter-spacing:1px;text-transform:uppercase;">
              Changes ( Old → New )
            </p>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border-radius:12px;border:1px solid #E3EAF0;
                          overflow:hidden;margin-bottom:24px;">
              <!-- Column headers -->
              <tr style="background:#ECEFF1;">
                <td style="padding:10px 16px;font-size:12px;font-weight:700;
                           color:#607D8B;text-transform:uppercase;
                           letter-spacing:0.5px;">Field</td>
                <td style="padding:10px 16px;text-align:center;font-size:12px;
                           font-weight:700;color:#E53935;text-transform:uppercase;
                           letter-spacing:0.5px;">Old</td>
                <td style="padding:10px 16px;text-align:center;"></td>
                <td style="padding:10px 16px;text-align:center;font-size:12px;
                           font-weight:700;color:#2E7D32;text-transform:uppercase;
                           letter-spacing:0.5px;">New</td>
              </tr>
              {rows_html}
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


# ─────────────────────────────────────────────────────────────
# Mail helper  — reuses mail.py shared SMTP + lock
# ─────────────────────────────────────────────────────────────
def send_edit_alert(
    transaction_id: str,
    edited_by:      str,
    date:           str,
    start_time:     str,
    end_time:       str,
    old:            dict,
    new:            dict,
):
    if not EDIT_ALERT_RECIPIENTS:
        logger.warning("EDIT_ALERT_MAIL is empty — skipping edit alert mail")
        return

    end_display = end_time if end_time and end_time.lower() != "none" else "Still running"

    subject = f"✏️ Transaction Edited — {transaction_id} — {date}"

    # Plain-text fallback
    plain = (
        f"Transaction Edit Alert — JL-CAM\n\n"
        f"Transaction ID : {transaction_id}\n"
        f"Date           : {date}\n"
        f"Start Time     : {start_time}\n"
        f"End Time       : {end_display}\n"
        f"Edited By      : {edited_by}\n\n"
        f"Changes (Old → New):\n"
        f"  Vehicle : {old['vehicle']} → {new['vehicle']}\n"
        f"  Box     : {old['box']}     → {new['box']}\n"
        f"  Bale    : {old['bale']}    → {new['bale']}\n"
        f"  Bag     : {old['bag']}     → {new['bag']}\n"
        f"  Trolley : {old['trolley']} → {new['trolley']}\n"
    )

    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = MAIL_USER
        msg["To"]      = ", ".join(EDIT_ALERT_RECIPIENTS)
        msg["Subject"] = subject

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(
            _build_edit_html(transaction_id, edited_by, date,
                             start_time, end_time, old, new),
            "html"
        ))

        server = get_smtp_connection()
        if not server:
            logger.error("SMTP server unavailable — edit alert mail not sent")
            return

        with smtp_lock:
            server.sendmail(MAIL_USER, EDIT_ALERT_RECIPIENTS, msg.as_string())

        logger.info(f"Edit alert mail sent → {EDIT_ALERT_RECIPIENTS}")

    except Exception:
        # Mail failure must NOT fail the API response
        logger.exception("Edit alert mail failed — DB update was still saved")


# ─────────────────────────────────────────────────────────────
# Request body — all fields optional
# ─────────────────────────────────────────────────────────────
class EditTransactionRequest(BaseModel):
    box_count:      Optional[int] = None
    bale_count:     Optional[int] = None
    bag_count:      Optional[int] = None
    trolley_count:  Optional[int] = None
    vehicle_number: Optional[str] = None
    edited_by:      Optional[str] = "Dashboard User"   # sent from Android


# ─────────────────────────────────────────────────────────────
# PUT /api/transactions/{transaction_id}
# ─────────────────────────────────────────────────────────────
@router.put("/api/transactions/{transaction_id}")
def edit_transaction(transaction_id: str, body: EditTransactionRequest):
    """
    Partially update a transaction.
    Sends an edit-alert mail with old vs new values on success.
    """

    updates = {}
    if body.box_count      is not None: updates["box_count"]      = body.box_count
    if body.bale_count     is not None: updates["bale_count"]     = body.bale_count
    if body.bag_count      is not None: updates["bag_count"]      = body.bag_count
    if body.trolley_count  is not None: updates["trolley_count"]  = body.trolley_count
    if body.vehicle_number is not None: updates["vehicle_number"] = body.vehicle_number

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    logger.info(f"Edit request → id={transaction_id} fields={list(updates.keys())} by={body.edited_by}")

    conn = None
    try:
        conn = get_connection()
        cur  = conn.cursor()

        # ── Step 1: Read OLD values ───────────────────────────
        cur.execute("""
            SELECT box_count, bale_count, bag_count, trolley_count,
                   vehicle_number, start_time, end_time, date
            FROM transaction_db
            WHERE transaction_id = %s
        """, (transaction_id,))

        old_row = cur.fetchone()
        if not old_row:
            raise HTTPException(status_code=404, detail="Transaction not found")

        old_box, old_bale, old_bag, old_trolley, \
            old_vehicle, start_time, end_time, date = old_row

        old = {
            "box":     old_box     or 0,
            "bale":    old_bale    or 0,
            "bag":     old_bag     or 0,
            "trolley": old_trolley or 0,
            "vehicle": old_vehicle or "",
        }

        # ── Step 2: Apply UPDATE ──────────────────────────────
        set_clause = (
            ", ".join(f"{col} = %s" for col in updates)
            + ", updated_at = CURRENT_TIMESTAMP"
        )
        values = list(updates.values()) + [transaction_id]

        cur.execute(
            f"""
            UPDATE transaction_db
            SET {set_clause}
            WHERE transaction_id = %s
            RETURNING transaction_id, box_count, bale_count, bag_count,
                      trolley_count, vehicle_number;
            """,
            values,
        )
        conn.commit()

        new_row = cur.fetchone()
        cur.close()

        if not new_row:
            raise HTTPException(status_code=404, detail="Transaction not found after update")

        new = {
            "box":     new_row[1] or 0,
            "bale":    new_row[2] or 0,
            "bag":     new_row[3] or 0,
            "trolley": new_row[4] or 0,
            "vehicle": new_row[5] or old["vehicle"],
        }

        logger.info(f"Transaction {transaction_id} updated OK")

        # ── Step 3: Send alert mail (non-blocking on failure) ─
        send_edit_alert(
            transaction_id = transaction_id,
            edited_by      = body.edited_by or "Dashboard User",
            date           = str(date       or ""),
            start_time     = str(start_time or ""),
            end_time       = str(end_time   or ""),
            old            = old,
            new            = new,
        )

        return {
            "success":        True,
            "transaction_id": new_row[0],
            "box_count":      new_row[1],
            "bale_count":     new_row[2],
            "bag_count":      new_row[3],
            "trolley_count":  new_row[4],
            "vehicle_number": new_row[5],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Edit transaction failed for {transaction_id}: {e}", exc_info=True)
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")
    finally:
        if conn:
            conn.close()