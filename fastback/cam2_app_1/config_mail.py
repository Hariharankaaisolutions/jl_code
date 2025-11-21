"""
Configuration file for application settings
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class EmailConfig:
    """Email configuration using Zoho SMTP"""
    SMTP_SERVER = "smtp.zoho.in"
    SMTP_PORT = 587
    USERNAME = os.getenv("SMTP_USERNAME")
    PASSWORD = os.getenv("SMTP_PASSWORD")
    FROM_EMAIL = USERNAME  # Zoho uses the same as username
    TO_EMAIL = os.getenv("TO_EMAIL").replace(" ", "").split(",")
    
    @classmethod
    def validate(cls):
        """Validate required environment variables"""
        if not all([cls.USERNAME, cls.PASSWORD, cls.TO_EMAIL]):
            raise ValueError(
                "Email configuration incomplete. Please set the following in your environment:\n"
                "SMTP_USERNAME, SMTP_PASSWORD, TO_EMAIL"
            )


class DetectionConfig:
    """Detection and YOLO model configuration"""
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
    MAX_BYTES = 5 * 1024 * 1024  # 5 MB
    BACKUP_COUNT = 3


# Validate configuration on import
EmailConfig.validate()
