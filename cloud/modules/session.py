# modules/session.py

import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import psycopg2

from utils_config_loader import load_properties
from logger import get_logger

IST = timezone(timedelta(hours=5, minutes=30))

router = APIRouter(tags=["Session Auth"])

logger = get_logger("session")
CONFIG = load_properties("config.properties")

DB_CONFIG = {
    "host": CONFIG.get("DB_HOST", "localhost"),
    "database": CONFIG.get("DB_NAME", "jlmill"),
    "user": CONFIG.get("DB_USER", "kaai"),
    "password": CONFIG.get("DB_PASSWORD", "yourpassword")
}

SESSION_TIMEOUT_HOURS = int(CONFIG.get("SESSION_TIMEOUT_HOURS", "5"))


def get_conn():
    """Create and return a new database connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}", exc_info=True)
        raise


def create_session(user_id: str):
    """Create a new session for a given user."""
    session_id = str(uuid.uuid4())
    start_time = datetime.utcnow()
    end_time = start_time + timedelta(hours=SESSION_TIMEOUT_HOURS)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO session_db (session_id, user_id, session_start_time, session_end_time)
        VALUES (%s, %s, %s, %s)
        """,
        (session_id, user_id, start_time, end_time),
    )
    conn.commit()
    cur.close()
    conn.close()

    logger.info(f"Session created for user {user_id} — ID: {session_id}")
    return session_id, end_time


def end_session(session_id: str):
    """Terminate a session manually (e.g., when app closes)."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE session_db
        SET session_end_time = %s
        WHERE session_id = %s
        """,
        (datetime.utcnow(), session_id),
    )
    conn.commit()
    cur.close()
    conn.close()

    logger.info(f"Session {session_id} terminated manually.")


@router.post("/api/auth/login")
async def login(request: Request):
    """Unified login endpoint — uses only user_id and device_id."""
    try:
        data = await request.json()
        user_id = data.get("user_id")
        device_id = data.get("device_id")

        if not user_id or not device_id:
            return JSONResponse({"success": False, "message": "Missing user_id or device_id"})

        conn = get_conn()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id, name, role
            FROM user_data
            WHERE user_id = %s AND device_unique_id = %s
            """,
            (user_id, device_id),
        )
        user = cur.fetchone()
        conn.close()

        if not user:
            logger.warning(f"Invalid login attempt — user_id={user_id}, device_id={device_id}")
            return JSONResponse({"success": False, "message": "Invalid user or device"})

        session_id, expiry = create_session(user_id)
        logger.info(f"User {user_id} logged in successfully.")

        return JSONResponse(
            {
                "success": True,
                "message": "Login successful",
                "session": {
                    "session_id": session_id,
                    "expires_at": expiry.isoformat()
                },
                "user": {
                    "user_id": user[0],
                    "name": user[1],
                    "role": user[2]
                },
            }
        )

    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        return JSONResponse({"success": False, "message": "Internal server error"})


@router.post("/api/auth/session_check")
async def session_check(request: Request):
    """Check if a given session is still valid."""
    try:
        data = await request.json()
        session_id = data.get("session_id")

        if not session_id:
            return JSONResponse({"success": False, "message": "Session ID missing"})

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT user_id, session_end_time
            FROM session_db
            WHERE session_id = %s
            """,
            (session_id,),
        )
        session = cur.fetchone()
        conn.close()

        if not session:
            return JSONResponse({"success": False, "message": "Session not found"})

        user_id, session_end_time = session
        if datetime.utcnow() > session_end_time:
            logger.info(f"Session expired: {session_id}")
            return JSONResponse({"success": False, "message": "Session expired"})

        return JSONResponse({"success": True, "message": "Session valid", "user_id": user_id})

    except Exception as e:
        logger.error(f"Session check error: {e}", exc_info=True)
        return JSONResponse({"success": False, "message": "Internal server error"})


@router.post("/api/auth/logout")
async def logout(request: Request):
    """Manually terminate a session when the app closes."""
    try:
        data = await request.json()
        session_id = data.get("session_id")

        if not session_id:
            return JSONResponse({"success": False, "message": "Session ID missing"})

        end_session(session_id)
        return JSONResponse({"success": True, "message": "Session terminated successfully"})

    except Exception as e:
        logger.error(f"Logout error: {e}", exc_info=True)
        return JSONResponse({"success": False, "message": "Internal server error"})
