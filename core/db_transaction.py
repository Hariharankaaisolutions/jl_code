"""
core/db_transaction.py — Transaction DB Operations
====================================================
All operations on transaction_db table.
Used by both cam1 and cam2 API.
Max 120 lines. One responsibility: transaction_db CRUD.
"""

import psycopg2
import psycopg2.pool
from datetime import datetime, date
from typing import Optional

from core.config import get, getint
from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("DB")

# ── Connection pool ────────────────────────────────────────────
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    try:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=getint("DB_POOL_MIN", 1),
            maxconn=getint("DB_POOL_MAX", 10),
            dbname=get("DB_NAME",     "jlmill"),
            user=get("DB_USER",       "kaai"),
            password=get("DB_PASSWORD", ""),
            host=get("DB_HOST",       "localhost"),
            port=getint("DB_PORT",    5432),
        )
        logger.info(LOG("DB.001.INFO",
            db=get("DB_NAME"), host=get("DB_HOST"), port=get("DB_PORT")))
        return _pool
    except Exception as e:
        logger.error(LOG("DB.002.ERROR", error=e))
        raise


def _conn():
    return _get_pool().getconn()


def _put(conn):
    try:
        _get_pool().putconn(conn)
    except Exception:
        pass


def insert_transaction(
    transaction_id: str,
    session_id: str,
    name: str,
    role: str,
    user_id: str,
    device_unique_id: str,
    cam: str,
    vehicle_number: str,
    start_time: str,
    image_path: Optional[str] = None,
) -> bool:
    conn = None
    try:
        conn = _conn()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO transaction_db
            (transaction_id, session_id, name, role, user_id,
             device_unique_id, cam, vehicle_number, date,
             start_time, image_path)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (transaction_id, session_id, name, role, user_id,
              device_unique_id, cam, vehicle_number,
              date.today(), start_time, image_path))
        conn.commit()
        logger.info(LOG("DB.005.INFO",
            tx_id=transaction_id[:8], session_id=session_id[:8]))
        return True
    except Exception as e:
        logger.error(LOG("DB.006.ERROR",
            tx_id=transaction_id[:8], error=e))
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            _put(conn)


def update_counts(
    transaction_id: str,
    box_count: int = 0,
    bale_count: int = 0,
    bag_count: int = 0,
    trolley_count: int = 0,
    image_path: Optional[str] = None,
) -> bool:
    conn = None
    try:
        conn = _conn()
        cur  = conn.cursor()
        cur.execute("""
            UPDATE transaction_db SET
                box_count=%s, bale_count=%s, bag_count=%s,
                trolley_count=%s, image_path=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE transaction_id=%s
        """, (box_count, bale_count, bag_count,
              trolley_count, image_path, transaction_id))
        conn.commit()
        logger.info(LOG("DB.007.INFO",
            tx_id=transaction_id[:8], box=box_count, bale=bale_count))
        return True
    except Exception as e:
        logger.error(LOG("DB.008.ERROR",
            tx_id=transaction_id[:8], error=e))
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            _put(conn)


def end_transaction(
    transaction_id: str,
    end_time: str,
    box_count: int = 0,
    bale_count: int = 0,
    bag_count: int = 0,
    trolley_count: int = 0,
    image_path: Optional[str] = None,
) -> bool:
    conn = None
    try:
        conn = _conn()
        cur  = conn.cursor()
        cur.execute("""
            UPDATE transaction_db SET
                end_time=%s, box_count=%s, bale_count=%s,
                bag_count=%s, trolley_count=%s,
                image_path=%s, updated_at=CURRENT_TIMESTAMP
            WHERE transaction_id=%s
        """, (end_time, box_count, bale_count, bag_count,
              trolley_count, image_path, transaction_id))
        conn.commit()
        logger.info(LOG("DB.009.INFO",
            tx_id=transaction_id[:8], end_time=end_time))
        return True
    except Exception as e:
        logger.error(LOG("DB.010.ERROR",
            tx_id=transaction_id[:8], error=e))
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            _put(conn)


def user_exists(user_id: str, device_id: str) -> bool:
    conn = None
    try:
        conn = _conn()
        cur  = conn.cursor()
        cur.execute("""
            SELECT 1 FROM user_data
            WHERE user_id=%s AND device_unique_id=%s LIMIT 1
        """, (user_id, device_id))
        exists = cur.fetchone() is not None
        if not exists:
            logger.warning(LOG("DB.022.WARN",
                user_id=user_id, device_id=device_id))
        return exists
    except Exception as e:
        logger.error(LOG("DB.023.ERROR", error=e))
        return False
    finally:
        if conn:
            _put(conn)
