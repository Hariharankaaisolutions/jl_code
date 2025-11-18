"""
Configuration file for application settings
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Load environment variables from .env file (optional but recommended)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use system env vars


class EmailConfig:
    """Email configuration"""
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    USERNAME = os.getenv("SMTP_USERNAME")
    PASSWORD = os.getenv("SMTP_PASSWORD")
    FROM_EMAIL = os.getenv("SMTP_USERNAME")  # Same as username for Gmail
    TO_EMAIL = os.getenv("TO_EMAIL")
    
    @classmethod
    def validate(cls):
        """Validate that all required email settings are configured"""
        if not all([cls.USERNAME, cls.PASSWORD, cls.TO_EMAIL]):
            raise ValueError(
                "Email configuration incomplete. Please set environment variables:\n"
                "SMTP_USERNAME, SMTP_PASSWORD, TO_EMAIL"
            )


class DetectionConfig:
    """Detection and model configuration"""
    YOLOV5_PATH = "yolov5"
    MODEL_PATH = "jlcam1final.pt"
    FRAME_WIDTH = 640
    FRAME_HEIGHT = 480
    X_LINE = 400
    CONF_THRES = 0.4


class LogConfig:
    """Logging configuration"""
    LOG_DIR = "logs"
    LOG_FILE = "app.log"
    MAX_BYTES = 5 * 1024 * 1024  # 5MB
    BACKUP_COUNT = 3


# Validate configuration on import
EmailConfig.validate()
