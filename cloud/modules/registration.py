# modules/registration.py

from fastapi import APIRouter, HTTPException
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel
from typing import Optional
import random
import psycopg2

from .mail import get_smtp_connection, send_mail, close_smtp_connection
from .role_manager import get_roles_for_otp
from utils_config_loader import load_properties
from logger import get_logger

router = APIRouter(tags=["User Registration"])
logger = get_logger("registration")

# Load config
CONFIG = load_properties("config.properties")

DB_NAME = CONFIG.get("DB_NAME", "jlmill")
DB_USER = CONFIG.get("DB_USER", "kaai")
DB_PASSWORD = CONFIG.get("DB_PASSWORD", "yourpassword")
DB_HOST = CONFIG.get("DB_HOST", "localhost")
DB_PORT = CONFIG.get("DB_PORT", "5432")

SEND_USER_MAIL = str(CONFIG.get("SEND_USER_MAIL", "false")).lower() == "true"

# Threadpool for parallel email sending
executor = ThreadPoolExecutor(max_workers=10)


class RegisterRequest(BaseModel):
    name: str
    role: str
    device_unique_id: str
    company_name: str
    branch: str
    sub_branch: str
    password: str
    mail: Optional[str] = None


class OTPVerifyRequest(BaseModel):
    otp: str
    registration_data: RegisterRequest


def get_connection():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
            host=DB_HOST, port=DB_PORT
        )
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database connection failed")


# In-memory OTP store
otp_store: dict[str, str] = {}


def generate_user_id(role: str, company_name: str, branch: str) -> str:
    prefix = company_name[:2].lower() + role[:2].lower() + branch[:2].lower()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM user_data WHERE user_id LIKE %s", (prefix + "%",))
    existing_ids = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    nums = []
    for uid in existing_ids:
        try:
            nums.append(int(uid[-3:]))
        except:
            pass

    next_num = (max(nums) + 1) if nums else 1
    return f"{prefix}{next_num:03d}"


# ----------------------------------------------------------
# 🚀 FAST REGISTER ENDPOINT — Parallel Mail + SMTP Pooling
# ----------------------------------------------------------
@router.post("/register")
def register_user(data: RegisterRequest):
    logger.info(f"New registration request: {data.name} ({data.role})")

    # 1️⃣ Generate OTP
    otp = str(random.randint(1000, 9999))
    otp_store[data.device_unique_id] = otp

    # 2️⃣ Fetch approver emails
    conn = get_connection()
    cur = conn.cursor()

    role_sets = get_roles_for_otp(data.branch)

    # Business roles
    business_roles = role_sets["business"]["roles"]
    placeholders_business = ",".join(["%s"] * len(business_roles))
    cur.execute(
        f"SELECT mail FROM user_data WHERE UPPER(role) IN ({placeholders_business})",
        business_roles,
    )
    business_mails = [r[0] for r in cur.fetchall() if r[0] and str(r[0]).lower() != "none"]

    # IT roles
    it_roles = role_sets["it"]["roles"]
    placeholders_it = ",".join(["%s"] * len(it_roles))

    if role_sets["it"]["branch_restricted"]:
        cur.execute(
            f"""
            SELECT mail FROM user_data
            WHERE UPPER(role) IN ({placeholders_it})
            AND UPPER(branch) = UPPER(%s)
            """,
            (*it_roles, data.branch),
        )
    else:
        cur.execute(
            f"SELECT mail FROM user_data WHERE UPPER(role) IN ({placeholders_it})",
            it_roles,
        )

    it_mails = [r[0] for r in cur.fetchall() if r[0] and str(r[0]).lower() != "none"]

    cur.close()
    conn.close()

    all_recipients = list(set(business_mails + it_mails))
    logger.info(f"Approver emails found: {all_recipients}")

    user_data = {
        "name": data.name,
        "role": data.role,
        "otp": otp,
    }

    # 3️⃣ High-speed email delivery
    server = get_smtp_connection()
    if server:
        for mail_addr in all_recipients:
            executor.submit(
                send_mail,
                server,
                mail_addr,
                "🔐 New User Registration OTP (Approval Required)",
                user_data,
            )
    else:
        logger.error("SMTP connection failed. Emails not sent.")

    # 4️⃣ Optional: send OTP to the user
    if SEND_USER_MAIL and data.mail and str(data.mail).lower() != "none":
        if server:
            executor.submit(
                send_mail,
                server,
                data.mail,
                "🔐 Your Registration OTP",
                user_data,
            )
            logger.info(f"User OTP queued → {data.mail}")
    else:
        logger.info("User mail skipped or disabled")

    # 5️⃣ Close SMTP safely in background
    if server:
        executor.submit(close_smtp_connection, server)

    # Response returns instantly
    return {"message": "OTP sent to approvers", "status": "pending"}


# ----------------------------------------------------------
# 🔐 OTP VERIFICATION
# ----------------------------------------------------------
@router.post("/verify_otp")
def verify_otp(req: OTPVerifyRequest):
    device_id = req.registration_data.device_unique_id
    stored_otp = otp_store.get(device_id)

    if stored_otp != req.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    user_id = generate_user_id(
        req.registration_data.role,
        req.registration_data.company_name,
        req.registration_data.branch,
    )

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO user_data (
            user_id, name, role, device_unique_id,
            company_name, branch, sub_branch, password, mail
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            user_id,
            req.registration_data.name,
            req.registration_data.role,
            req.registration_data.device_unique_id,
            req.registration_data.company_name,
            req.registration_data.branch,
            req.registration_data.sub_branch,
            req.registration_data.password,
            req.registration_data.mail,
        ),
    )

    conn.commit()
    cur.close()
    conn.close()

    otp_store.pop(device_id, None)
    logger.info(f"User registered successfully → {user_id}")

    return {"message": "User registered successfully", "user_id": user_id}


# ----------------------------------------------------------
# 📋 List all users
# ----------------------------------------------------------
@router.get("/users")
def get_all_users():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM user_data ORDER BY user_id ASC")
    rows = cur.fetchall()

    col_names = [desc[0] for desc in cur.description]
    users = [dict(zip(col_names, row)) for row in rows]

    cur.close()
    conn.close()

    return {"total_users": len(users), "users": users}
