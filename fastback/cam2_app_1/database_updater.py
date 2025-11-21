# database_updater.py — Fully Converted to Message Codes
# =======================================================

from smart_logger import get_logger
logger = get_logger(__name__)

from message_loader import Messages   # <-- NEW

import psycopg2
from datetime import datetime

from config_loader import (
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
    DB_HOST,
    DB_PORT,
)


class DatabaseUpdater:
    def __init__(self):
        # DB.UPDATER.001.INFO = Initializing DatabaseUpdater (PostgreSQL)
        logger.info(Messages.get("DB.UPDATER.001.INFO"))

        try:
            self.conn = psycopg2.connect(
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=str(DB_PORT)
            )
            self.conn.autocommit = True
            self.cursor = self.conn.cursor()

            # DB.UPDATER.002.INFO = DatabaseUpdater connected successfully
            logger.info(Messages.get("DB.UPDATER.002.INFO"))

        except Exception:
            # DB.UPDATER.003.ERROR = DatabaseUpdater connection failed
            logger.exception(Messages.get("DB.UPDATER.003.ERROR"))


    # ----------------------------------------------------------------------
    # Update counts on multiple columns
    # ----------------------------------------------------------------------
    def update_counts_on_multiples(
        self,
        transaction_id,
        box_count,
        bale_count,
        bag_count,
        trolley_count,
        image_path
    ):
        logger.debug(
            Messages.get(
                "DB.UPDATER.004.DEBUG",
                transaction_id=transaction_id,
                box=box_count,
                bale=bale_count,
                bag=bag_count,
                trolley=trolley_count
            )
        )

        query = """
        UPDATE transaction_db SET
            box_count=%s,
            bale_count=%s,
            bag_count=%s,
            trolley_count=%s,
            image_path=%s,
            updated_at=CURRENT_TIMESTAMP
        WHERE transaction_id=%s;
        """

        params = (
            box_count,
            bale_count,
            bag_count,
            trolley_count,
            image_path,
            transaction_id
        )

        try:
            self.cursor.execute(query, params)

        except Exception:
            logger.exception(
                Messages.get("DB.UPDATER.005.ERROR", transaction_id=transaction_id)
            )

    # ----------------------------------------------------------------------
    # Close connection
    # ----------------------------------------------------------------------
    def close(self):
        try:
            self.cursor.close()
            self.conn.close()
            logger.info(Messages.get("DB.UPDATER.006.INFO"))

        except Exception:
            logger.exception(Messages.get("DB.UPDATER.007.ERROR"))
