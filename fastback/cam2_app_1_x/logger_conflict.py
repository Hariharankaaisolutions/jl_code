import logging
import os

LOG_DIR = "logs"
CONFLICT_LOG = "conflict.log"

def get_conflict_logger():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    log_path = os.path.join(LOG_DIR, CONFLICT_LOG)

    logger = logging.getLogger("conflict_logger")

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        handler = logging.FileHandler(log_path, mode="a")
        handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s — %(levelname)s — %(message)s",
            "%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)

    return logger
