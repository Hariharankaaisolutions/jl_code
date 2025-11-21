# logger.py
import logging
import os
import sys

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ExceptionFilter(logging.Filter):
    """Only pass records that have exception info."""
    def filter(self, record: logging.LogRecord) -> bool:
        return record.exc_info is not None


def get_logger(name: str = "app") -> logging.Logger:
    """
    Create or return a logger with:
      - logs/info.log      (INFO+)
      - logs/debug.log     (DEBUG+)
      - logs/warning.log   (WARNING+)
      - logs/error.log     (ERROR+)
      - logs/exception.log (ERROR+ with exc_info)
      - stdout stream handler (DEBUG+)
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Stream handler (console)
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    # Info handler
    info_handler = logging.FileHandler(os.path.join(LOG_DIR, "info.log"))
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)
    logger.addHandler(info_handler)

    # Debug handler
    debug_handler = logging.FileHandler(os.path.join(LOG_DIR, "debug.log"))
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(formatter)
    logger.addHandler(debug_handler)

    # Warning handler
    warning_handler = logging.FileHandler(os.path.join(LOG_DIR, "warning.log"))
    warning_handler.setLevel(logging.WARNING)
    warning_handler.setFormatter(formatter)
    logger.addHandler(warning_handler)

    # Error handler
    error_handler = logging.FileHandler(os.path.join(LOG_DIR, "error.log"))
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    # Exception handler – only for records with exc_info
    exception_handler = logging.FileHandler(os.path.join(LOG_DIR, "exception.log"))
    exception_handler.setLevel(logging.ERROR)
    exception_handler.setFormatter(formatter)
    exception_handler.addFilter(ExceptionFilter())
    logger.addHandler(exception_handler)

    return logger


# Optional: create a root app logger if you want to use it directly
logger = get_logger("main")
