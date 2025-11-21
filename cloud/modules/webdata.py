# modules/webdata.py

from fastapi import APIRouter, HTTPException
import psycopg2
import psycopg2.extras

from utils_config_loader import load_properties
from logger import get_logger

router = APIRouter(tags=["Web Data (Users for Web UI)"])
logger = get_logger("webdata")

CONFIG = load_properties("config.properties")

DB_CONFIG = {
    "dbname": CONFIG.get("DB_NAME", "jlmill"),
    "user": CONFIG.get("DB_USER", "kaai"),
    "password": CONFIG.get("DB_PASSWORD", "yourpassword"),
    "host": CONFIG.get("DB_HOST", "localhost"),
    "port": CONFIG.get("DB_PORT", "5432"),
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


@router.get("/web/users")
def get_all_users_web():
    """
    Returns all user data from PostgreSQL (except password for security).
    (Path changed from /users → /web/users to avoid conflict with registration /users)
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT 
                user_id, 
                name, 
                role, 
                device_unique_id,
                company_name,
                branch,
                sub_branch,
                mail
            FROM user_data
            ORDER BY name;
            """
        )
        users = cur.fetchall()
        cur.close()
        return {"users": users}
    except Exception as e:
        logger.error(f"Database error in webdata: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        if conn:
            conn.close()
