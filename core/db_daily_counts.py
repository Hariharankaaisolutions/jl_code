"""
core/db_daily_counts.py — Daily Counts DB Operations
======================================================
All operations on daily_counts table.
Tracks per-day totals for boot report and cloud API.
Max 100 lines. One responsibility: daily_counts CRUD.
"""

from datetime import date, timedelta
from typing import Optional

import psycopg2.pool

from core.config import get, getint
from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("DB")

# ── Reuse same pool as db_transaction ─────────────────────────
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    import psycopg2
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=getint("DB_POOL_MIN", 1),
        maxconn=getint("DB_POOL_MAX", 10),
        dbname=get("DB_NAME",       "jlmill"),
        user=get("DB_USER",         "kaai"),
        password=get("DB_PASSWORD", ""),
        host=get("DB_HOST",         "localhost"),
        port=getint("DB_PORT",      5432),
    )
    return _pool


def _conn():
    return _get_pool().getconn()


def _put(conn):
    try:
        _get_pool().putconn(conn)
    except Exception:
        pass


def upsert(
    session_id: str,
    transaction_id: str,
    cam: str,
    box_count: int = 0,
    bale_count: int = 0,
    trolley_count: int = 0,
    bag_count: int = 0,
) -> bool:
    conn = None
    try:
        today = date.today()
        conn  = _conn()
        cur   = conn.cursor()
        cur.execute("""
            INSERT INTO daily_counts
                (date, cam, session_id, transaction_id,
                 box_count, bale_count, trolley_count, bag_count,
                 created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
            ON CONFLICT (date, cam, transaction_id)
            DO UPDATE SET
                box_count=EXCLUDED.box_count,
                bale_count=EXCLUDED.bale_count,
                trolley_count=EXCLUDED.trolley_count,
                bag_count=EXCLUDED.bag_count,
                updated_at=NOW()
        """, (today, cam, session_id, transaction_id,
              box_count, bale_count, trolley_count, bag_count))
        conn.commit()
        logger.info(LOG("DB.011.INFO",
            date=today, cam=cam, box=box_count, bale=bale_count))
        return True
    except Exception as e:
        logger.error(LOG("DB.012.ERROR", error=e))
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            _put(conn)


def get_totals(cam: str = "cam_1", target_date: date = None) -> dict:
    conn = None
    try:
        target = target_date or date.today()
        conn   = _conn()
        cur    = conn.cursor()
        cur.execute("""
            SELECT COALESCE(SUM(box_count),0),
                   COALESCE(SUM(bale_count),0),
                   COALESCE(SUM(trolley_count),0),
                   COALESCE(SUM(bag_count),0),
                   COUNT(*)
            FROM daily_counts
            WHERE date=%s AND cam=%s
        """, (target, cam))
        row = cur.fetchone()
        logger.info(LOG("DB.013.INFO", date=target, cam=cam))
        return {
            "date": str(target), "cam": cam,
            "box": int(row[0]),  "bale": int(row[1]),
            "trolley": int(row[2]), "bag": int(row[3]),
            "session_count": int(row[4]),
        }
    except Exception as e:
        logger.error(LOG("DB.014.ERROR", error=e))
        return {"date": str(target_date or date.today()),
                "cam": cam, "box": 0, "bale": 0,
                "trolley": 0, "bag": 0, "session_count": 0}
    finally:
        if conn:
            _put(conn)


def get_yesterday_totals(cam: str = "cam_1") -> dict:
    yesterday = date.today() - timedelta(days=1)
    result    = get_totals(cam=cam, target_date=yesterday)
    logger.info(LOG("DB.015.INFO", date=yesterday, cam=cam))
    return result
