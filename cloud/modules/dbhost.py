# modules/dbhost.py

from fastapi import APIRouter, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware  # CORS handled in main
import psycopg2
from datetime import datetime

from utils_config_loader import load_properties
from logger import get_logger

router = APIRouter(tags=["DB Host API"])
logger = get_logger("dbhost")

CONFIG = load_properties("config.properties")

DB_CONFIG = {
    "dbname": CONFIG.get("DB_NAME", "jlmill"),
    "user": CONFIG.get("DB_USER", "kaai"),
    "password": CONFIG.get("DB_PASSWORD", "yourpassword"),
    "host": CONFIG.get("DB_HOST", "localhost"),
    "port": CONFIG.get("DB_PORT", "5432"),
}


def get_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        logger.error(f"Database connection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")


@router.get("/transactions/by-date")
def get_transactions_by_date(date: str = Query(..., description="Date in YYYY-MM-DD format")):
    """
    Fetch transactions from transaction_db for the given date,
    ordered by start_time in descending order.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        query = """
            SELECT
                transaction_id,
                session_id,
                name,
                role,
                user_id,
                device_unique_id,
                cam,
                vehicle_number,
                date,
                start_time,
                end_time,
                box_count,
                bale_count,
                bag_count,
                trolley_count,
                image_path,
                updated_at
            FROM transaction_db
            WHERE date = %s
            ORDER BY start_time DESC;
        """

        cur.execute(query, (date,))
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]

        cur.close()
        conn.close()

        results = [dict(zip(columns, row)) for row in rows]

        return {
            "count": len(results),
            "date": date,
            "data": results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching data by date: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching data: {e}")


@router.get("/db/status")
def db_status():
    return {"message": "Transaction Database API (router) active"}
