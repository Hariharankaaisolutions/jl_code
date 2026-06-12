# database.py — Fully Converted to Message Codes
# ==============================================

from smart_logger import get_logger
logger = get_logger(__name__)

from message_loader import Messages   # <-- NEW

import psycopg2
from psycopg2 import pool
from datetime import datetime

from mqtt_push import mqtt_push_error

from config_loader import (
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
    DB_HOST,
    DB_PORT,
)


class DetectionDatabase:
    def __init__(self,
                 dbname=DB_NAME,
                 user=DB_USER,
                 password=DB_PASSWORD,
                 host=DB_HOST,
                 port=str(DB_PORT)):

        logger.info(
            Messages.get(
                "DB.CONNECTION.001.INFO",
                dbname=dbname,
                user=user,
                host=host,
                port=port
            )
        )

        try:
            self.connection_pool = psycopg2.pool.SimpleConnectionPool(
                1, 20,
                dbname=dbname,
                user=user,
                password=password,
                host=host,
                port=port
            )

            if self.connection_pool:
                logger.info(Messages.get("DB.CONNECTION.002.INFO"))
                self.create_table()
            else:
                logger.error(Messages.get("DB.CONNECTION.003.ERROR"))

                mqtt_push_error(
                    session_id="db",
                    transaction_id="db",
                    error_code="DB.CONNECTION.003.ERROR",
                    message="Failed to create PostgreSQL connection pool",
                    severity="critical"
                )

        except Exception as e:
            logger.exception(Messages.get("DB.CONNECTION.004.ERROR"))

            self.connection_pool = None
            mqtt_push_error(
                session_id="db",
                transaction_id="db",
                error_code="DB.CONNECTION.004.ERROR",
                message=str(e),
                severity="critical"
            )

    # ----------------------------------------------------------------------
    # Create Table
    # ----------------------------------------------------------------------
    def create_table(self):
        logger.info(Messages.get("DB.TABLE.001.INFO"))

        query = """
        CREATE TABLE IF NOT EXISTS transaction_db (
            transaction_id VARCHAR PRIMARY KEY,
            session_id VARCHAR,
            name VARCHAR,
            role VARCHAR,
            user_id VARCHAR,
            device_unique_id VARCHAR,
            cam VARCHAR,
            vehicle_number VARCHAR,
            date DATE,
            start_time TIME,
            end_time TIME,
            box_count INTEGER DEFAULT 0,
            bale_count INTEGER DEFAULT 0,
            bag_count INTEGER DEFAULT 0,
            trolley_count INTEGER DEFAULT 0,
            image_path TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user_data(user_id) ON DELETE SET NULL
        );
        """

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_session ON transaction_db(session_id);",
            "CREATE INDEX IF NOT EXISTS idx_date ON transaction_db(date);"
        ]

        conn = None
        try:
            conn = self.connection_pool.getconn()
            cur = conn.cursor()

            cur.execute(query)
            for idx in indexes:
                cur.execute(idx)

            conn.commit()
            cur.close()

        except Exception as e:
            logger.exception(Messages.get("DB.TABLE.002.ERROR"))

            mqtt_push_error(
                session_id="db",
                transaction_id="db",
                error_code="DB.TABLE.002.ERROR",
                message=str(e),
                severity="high"
            )

            if conn:
                conn.rollback()

        finally:
            if conn:
                self.connection_pool.putconn(conn)

    # ----------------------------------------------------------------------
    # User Exists
    # ----------------------------------------------------------------------
    def user_exists(self, user_id, device_unique_id):
        logger.debug(
            Messages.get("DB.USER.001.DEBUG", user_id=user_id, device_id=device_unique_id)
        )

        query = """
        SELECT 1 FROM user_data
        WHERE user_id=%s AND device_unique_id=%s
        LIMIT 1;
        """

        conn = None
        try:
            conn = self.connection_pool.getconn()
            cur = conn.cursor()

            cur.execute(query, (user_id, device_unique_id))
            result = cur.fetchone()
            cur.close()

            exists = result is not None

            logger.debug(Messages.get("DB.USER.002.DEBUG", exists=exists))
            return exists

        except Exception as e:
            logger.exception(Messages.get("DB.USER.003.ERROR"))

            mqtt_push_error(
                session_id="auth",
                transaction_id="auth",
                error_code="DB.USER.003.ERROR",
                message=str(e),
                severity="high"
            )

            return False

        finally:
            if conn:
                self.connection_pool.putconn(conn)

    # ----------------------------------------------------------------------
    # Insert Session
    # ----------------------------------------------------------------------
    def insert_session(
        self,
        session_id,
        transaction_id,
        name,
        role,
        user_id,
        device_unique_id,
        cam,
        vehicle_number,
        start_time,
        image_path=None
    ):
        logger.info(
            Messages.get("DB.INSERT.001.INFO", session_id=session_id, transaction_id=transaction_id)
        )

        query = """
        INSERT INTO transaction_db
        (transaction_id, session_id, name, role, user_id, device_unique_id,
         cam, vehicle_number, date, start_time, image_path)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING transaction_id;
        """

        params = (
            transaction_id,
            session_id,
            name,
            role,
            user_id,
            device_unique_id,
            cam,
            vehicle_number,
            datetime.now().date(),
            start_time,
            image_path
        )

        conn = None
        try:
            conn = self.connection_pool.getconn()
            cur = conn.cursor()

            cur.execute(query, params)
            conn.commit()

            res = cur.fetchone()
            cur.close()

            if res:
                logger.info(Messages.get("DB.INSERT.002.INFO"))
                return transaction_id

            logger.error(Messages.get("DB.INSERT.003.ERROR"))
            mqtt_push_error(
                session_id=session_id,
                transaction_id=transaction_id,
                error_code="DB.INSERT.003.ERROR",
                message="Insert returned no result",
                severity="high"
            )
            return None

        except Exception as e:
            logger.exception(Messages.get("DB.INSERT.004.ERROR"))

            mqtt_push_error(
                session_id=session_id,
                transaction_id=transaction_id,
                error_code="DB.INSERT.004.ERROR",
                message=str(e),
                severity="critical"
            )

            if conn:
                conn.rollback()

            return None

        finally:
            if conn:
                self.connection_pool.putconn(conn)

    # ----------------------------------------------------------------------
    # Update Session End
    # ----------------------------------------------------------------------
    def update_session_end(self,
                           transaction_id,
                           end_time,
                           box_count,
                           bale_count,
                           bag_count,
                           trolley_count,
                           image_path):

        logger.info(
            Messages.get("DB.UPDATE.001.INFO", transaction_id=transaction_id)
        )

        query = """
        UPDATE transaction_db SET
            end_time=%s,
            box_count=%s,
            bale_count=%s,
            bag_count=%s,
            trolley_count=%s,
            image_path=%s,
            updated_at=CURRENT_TIMESTAMP
        WHERE transaction_id=%s;
        """

        params = (
            end_time,
            box_count,
            bale_count,
            bag_count,
            trolley_count,
            image_path,
            transaction_id
        )

        conn = None
        try:
            conn = self.connection_pool.getconn()
            cur = conn.cursor()

            cur.execute(query, params)
            conn.commit()

            rows = cur.rowcount
            cur.close()

            if rows <= 0:
                logger.error(Messages.get("DB.UPDATE.002.ERROR"))

                mqtt_push_error(
                    session_id="session",
                    transaction_id=transaction_id,
                    error_code="DB.UPDATE.002.ERROR",
                    message="No rows updated for session end",
                    severity="high"
                )

            return rows > 0

        except Exception as e:
            logger.exception(Messages.get("DB.UPDATE.003.ERROR"))

            mqtt_push_error(
                session_id="session",
                transaction_id=transaction_id,
                error_code="DB.UPDATE.003.ERROR",
                message=str(e),
                severity="critical"
            )

            if conn:
                conn.rollback()

            return False

        finally:
            if conn:
                self.connection_pool.putconn(conn)

    # ----------------------------------------------------------------------
    # Select Sessions by Date
    # ----------------------------------------------------------------------
    def get_sessions_by_date(self, date):
        logger.info(
            Messages.get("DB.SELECT.001.INFO", date=date)
        )

        query = """
        SELECT
            transaction_id, session_id, name, role,
            user_id, device_unique_id, cam, vehicle_number,
            date, start_time, end_time,
            box_count, bale_count, bag_count, trolley_count,
            image_path, updated_at
        FROM transaction_db
        WHERE date=%s
        ORDER BY start_time DESC;
        """

        conn = None
        try:
            conn = self.connection_pool.getconn()
            cur = conn.cursor()

            cur.execute(query, (date,))
            rows = cur.fetchall()
            cur.close()

            cols = [
                "transaction_id", "session_id", "name", "role",
                "user_id", "device_unique_id", "cam", "vehicle_number",
                "date", "start_time", "end_time",
                "box_count", "bale_count", "bag_count", "trolley_count",
                "image_path", "updated_at"
            ]

            return [dict(zip(cols, row)) for row in rows]

        except Exception as e:
            logger.exception(Messages.get("DB.SELECT.002.ERROR"))

            mqtt_push_error(
                session_id="history",
                transaction_id="history",
                error_code="DB.SELECT.002.ERROR",
                message=str(e),
                severity="medium"
            )

            return []

        finally:
            if conn:
                self.connection_pool.putconn(conn)
