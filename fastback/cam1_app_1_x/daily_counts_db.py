# daily_counts_db.py — Daily Counts Database Handler
# ===================================================
# Manages the daily_counts table in PostgreSQL
# Updates counts on every detection event
# Provides daily summary for boot report and cloud API
# ===================================================

import os
import psycopg2
import psycopg2.pool
from datetime import datetime, date
from typing import Optional

from jl_logger import get_logger

logger = get_logger("DATABASE")

# ─────────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────────
_PROPS_FILE = os.path.join(os.path.dirname(__file__), "app.properties")

def _load_props() -> dict:
    props = {}
    try:
        with open(_PROPS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
    except Exception:
        pass
    return props

_props      = _load_props()
DB_NAME     = _props.get("DB_NAME",     "jlmill")
DB_USER     = _props.get("DB_USER",     "kaai")
DB_PASSWORD = _props.get("DB_PASSWORD", "yourpassword")
DB_HOST     = _props.get("DB_HOST",     "localhost")
DB_PORT     = int(_props.get("DB_PORT", "5432"))
ENABLED     = _props.get("DAILY_COUNTS_ENABLED", "true").lower() == "true"


# ─────────────────────────────────────────────────
# Connection pool
# ─────────────────────────────────────────────────
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=5,
                dbname=DB_NAME, user=DB_USER,
                password=DB_PASSWORD, host=DB_HOST, port=DB_PORT
            )
            logger.info(f"Daily counts DB pool created → {DB_NAME}@{DB_HOST}:{DB_PORT}")
        except Exception as e:
            logger.error(f"Daily counts DB pool failed: {e}", exc_info=True)
            raise
    return _pool

def _get_conn():
    return _get_pool().getconn()

def _put_conn(conn):
    try:
        _get_pool().putconn(conn)
    except Exception:
        pass


# ─────────────────────────────────────────────────
# Upsert daily counts
# ─────────────────────────────────────────────────
def upsert_daily_counts(
    session_id:     str,
    transaction_id: str,
    cam:            str,
    box_count:      int = 0,
    bale_count:     int = 0,
    trolley_count:  int = 0,
    bag_count:      int = 0,
) -> bool:
    """
    Insert or update today's counts for this transaction.
    Called on every count update during detection.

    Returns True on success, False on failure.
    """
    if not ENABLED:
        return True

    conn = None
    try:
        today = date.today()
        conn  = _get_conn()
        cur   = conn.cursor()

        cur.execute("""
            INSERT INTO daily_counts
                (date, cam, session_id, transaction_id,
                 box_count, bale_count, trolley_count, bag_count,
                 created_at, updated_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (date, cam, transaction_id)
            DO UPDATE SET
                box_count     = EXCLUDED.box_count,
                bale_count    = EXCLUDED.bale_count,
                trolley_count = EXCLUDED.trolley_count,
                bag_count     = EXCLUDED.bag_count,
                updated_at    = NOW()
        """, (today, cam, session_id, transaction_id,
              box_count, bale_count, trolley_count, bag_count))

        conn.commit()
        logger.info(
            f"daily_counts updated → date={today} cam={cam} "
            f"box={box_count} bale={bale_count} trolley={trolley_count} "
            f"bag={bag_count} tx={transaction_id[:8]}"
        )
        return True

    except Exception as e:
        logger.error(f"upsert_daily_counts failed: {e}", exc_info=True)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False

    finally:
        if conn:
            _put_conn(conn)


# ─────────────────────────────────────────────────
# Get today's totals
# ─────────────────────────────────────────────────
def get_today_totals(cam: str = "cam_1") -> dict:
    """
    Get sum of all counts for today for given camera.
    Used by boot report and cloud API.
    """
    conn = None
    try:
        today = date.today()
        conn  = _get_conn()
        cur   = conn.cursor()

        cur.execute("""
            SELECT
                COALESCE(SUM(box_count),     0) AS box,
                COALESCE(SUM(bale_count),    0) AS bale,
                COALESCE(SUM(trolley_count), 0) AS trolley,
                COALESCE(SUM(bag_count),     0) AS bag,
                COUNT(*) AS session_count
            FROM daily_counts
            WHERE date = %s AND cam = %s
        """, (today, cam))

        row = cur.fetchone()
        result = {
            "date":          str(today),
            "cam":           cam,
            "box":           int(row[0]),
            "bale":          int(row[1]),
            "trolley":       int(row[2]),
            "bag":           int(row[3]),
            "session_count": int(row[4]),
        }
        logger.info(
            f"today totals → date={today} cam={cam} "
            f"box={result['box']} bale={result['bale']} "
            f"trolley={result['trolley']} sessions={result['session_count']}"
        )
        return result

    except Exception as e:
        logger.error(f"get_today_totals failed: {e}", exc_info=True)
        return {
            "date": str(date.today()), "cam": cam,
            "box": 0, "bale": 0, "trolley": 0, "bag": 0, "session_count": 0
        }

    finally:
        if conn:
            _put_conn(conn)


# ─────────────────────────────────────────────────
# Get yesterday's totals (for boot report)
# ─────────────────────────────────────────────────
def get_yesterday_totals(cam: str = "cam_1") -> dict:
    """Get sum of all counts for yesterday. Used by boot report email."""
    conn = None
    try:
        from datetime import timedelta
        yesterday = date.today() - timedelta(days=1)
        conn      = _get_conn()
        cur       = conn.cursor()

        cur.execute("""
            SELECT
                COALESCE(SUM(box_count),     0),
                COALESCE(SUM(bale_count),    0),
                COALESCE(SUM(trolley_count), 0),
                COALESCE(SUM(bag_count),     0),
                COUNT(*)
            FROM daily_counts
            WHERE date = %s AND cam = %s
        """, (yesterday, cam))

        row = cur.fetchone()
        result = {
            "date":          str(yesterday),
            "cam":           cam,
            "box":           int(row[0]),
            "bale":          int(row[1]),
            "trolley":       int(row[2]),
            "bag":           int(row[3]),
            "session_count": int(row[4]),
        }
        logger.info(
            f"yesterday totals → date={yesterday} cam={cam} "
            f"box={result['box']} bale={result['bale']} "
            f"trolley={result['trolley']} sessions={result['session_count']}"
        )
        return result

    except Exception as e:
        logger.error(f"get_yesterday_totals failed: {e}", exc_info=True)
        return {
            "date": str(date.today()), "cam": cam,
            "box": 0, "bale": 0, "trolley": 0, "bag": 0, "session_count": 0
        }

    finally:
        if conn:
            _put_conn(conn)


# ─────────────────────────────────────────────────
# Upsert MOG2 buffer log
# ─────────────────────────────────────────────────
def upsert_mog2_log(
    session_id:       str,
    transaction_id:   str,
    cam:              str,
    total_frames:     int = 0,
    motion_frames:    int = 0,
    skipped_frames:   int = 0,
    yolox_processed:  int = 0,
    cpu_pauses:       int = 0,
    avg_inference_ms: float = 0.0,
) -> bool:
    """Update MOG2 processing stats for this session."""
    conn = None
    try:
        today = date.today()
        conn  = _get_conn()
        cur   = conn.cursor()

        cur.execute("""
            INSERT INTO mog2_buffer_log
                (date, session_id, transaction_id, cam,
                 total_frames, motion_frames, skipped_frames,
                 yolox_processed, cpu_pauses, avg_inference_ms,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT DO NOTHING
        """, (today, session_id, transaction_id, cam,
              total_frames, motion_frames, skipped_frames,
              yolox_processed, cpu_pauses, avg_inference_ms))

        # Update if exists
        cur.execute("""
            UPDATE mog2_buffer_log SET
                total_frames     = %s,
                motion_frames    = %s,
                skipped_frames   = %s,
                yolox_processed  = %s,
                cpu_pauses       = %s,
                avg_inference_ms = %s,
                updated_at       = NOW()
            WHERE transaction_id = %s AND date = %s
        """, (total_frames, motion_frames, skipped_frames,
              yolox_processed, cpu_pauses, avg_inference_ms,
              transaction_id, today))

        conn.commit()
        return True

    except Exception as e:
        logger.error(f"upsert_mog2_log failed: {e}", exc_info=True)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False

    finally:
        if conn:
            _put_conn(conn)

