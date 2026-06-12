# delete_video.py — Converted to Message Codes (SYSTEM.VIDEO_CLEANUP.*)
# ====================================================================

from smart_logger import get_logger
logger = get_logger(__name__)

from message_loader import Messages  # <-- NEW

import os
from datetime import datetime, timedelta
from pathlib import Path


class VideoCleanup:
    def __init__(self, video_dir="detection_videos", days_to_keep=10):
        """
        Initialize VideoCleanup
        """
        logger.info(
            Messages.get(
                "SYSTEM.VIDEO_CLEANUP.010.INFO",
                video_dir=video_dir,
                days_to_keep=days_to_keep
            )
        )

        self.video_dir = video_dir
        self.days_to_keep = days_to_keep
        self.cutoff_date = datetime.now() - timedelta(days=days_to_keep)

        if not os.path.exists(video_dir):
            logger.warning(
                Messages.get("SYSTEM.VIDEO_CLEANUP.011.WARN", video_dir=video_dir)
            )
        else:
            logger.info(
                Messages.get(
                    "SYSTEM.VIDEO_CLEANUP.012.INFO",
                    video_dir=video_dir,
                    days_to_keep=days_to_keep
                )
            )

        logger.debug(
            Messages.get("SYSTEM.VIDEO_CLEANUP.013.DEBUG", cutoff=str(self.cutoff_date))
        )

    # ------------------------------------------------------------------
    # File Age
    # ------------------------------------------------------------------
    def get_file_age_days(self, filepath):
        logger.debug(Messages.get("SYSTEM.VIDEO_CLEANUP.014.DEBUG", filepath=filepath))

        try:
            file_time = os.path.getmtime(filepath)
            file_date = datetime.fromtimestamp(file_time)
            age_days = (datetime.now() - file_date).days

            logger.debug(
                Messages.get(
                    "SYSTEM.VIDEO_CLEANUP.015.DEBUG",
                    filename=os.path.basename(filepath),
                    age_days=age_days
                )
            )
            return age_days

        except Exception:
            logger.exception(
                Messages.get("SYSTEM.VIDEO_CLEANUP.016.ERROR", filepath=filepath)
            )
            return 0

    # ------------------------------------------------------------------
    # Old File Check
    # ------------------------------------------------------------------
    def is_old_file(self, filepath):
        logger.debug(
            Messages.get(
                "SYSTEM.VIDEO_CLEANUP.017.DEBUG",
                cutoff=str(self.cutoff_date),
                filepath=filepath
            )
        )

        try:
            file_time = os.path.getmtime(filepath)
            file_date = datetime.fromtimestamp(file_time)
            old = file_date < self.cutoff_date

            logger.debug(
                Messages.get(
                    "SYSTEM.VIDEO_CLEANUP.018.DEBUG",
                    filename=os.path.basename(filepath),
                    old=old,
                    file_date=file_date
                )
            )

            return old

        except Exception:
            logger.exception(
                Messages.get("SYSTEM.VIDEO_CLEANUP.019.ERROR", filepath=filepath)
            )
            return False

    # ------------------------------------------------------------------
    # Scan for Old Files
    # ------------------------------------------------------------------
    def get_old_files(self):
        logger.info(
            Messages.get("SYSTEM.VIDEO_CLEANUP.020.INFO", video_dir=self.video_dir)
        )

        if not os.path.exists(self.video_dir):
            logger.warning(
                Messages.get("SYSTEM.VIDEO_CLEANUP.021.WARN", video_dir=self.video_dir)
            )
            return []

        old_files = []

        try:
            for filename in os.listdir(self.video_dir):
                filepath = os.path.join(self.video_dir, filename)

                logger.debug(
                    Messages.get("SYSTEM.VIDEO_CLEANUP.022.DEBUG", filepath=filepath)
                )

                if os.path.isdir(filepath):
                    logger.debug(
                        Messages.get("SYSTEM.VIDEO_CLEANUP.023.DEBUG", filepath=filepath)
                    )
                    continue

                if self.is_old_file(filepath):
                    old_files.append(filepath)
                    logger.debug(
                        Messages.get("SYSTEM.VIDEO_CLEANUP.024.DEBUG", filepath=filepath)
                    )

        except Exception:
            logger.exception(
                Messages.get("SYSTEM.VIDEO_CLEANUP.004.ERROR", video_dir=self.video_dir)
            )

        logger.info(
            Messages.get("SYSTEM.VIDEO_CLEANUP.025.INFO", count=len(old_files))
        )
        return old_files

    # ------------------------------------------------------------------
    # Delete Old Videos
    # ------------------------------------------------------------------
    def delete_old_videos(self):
        logger.info(Messages.get("SYSTEM.VIDEO_CLEANUP.026.INFO"))

        old_files = self.get_old_files()

        if not old_files:
            logger.info(
                Messages.get(
                    "SYSTEM.VIDEO_CLEANUP.003.INFO",
                    days_to_keep=self.days_to_keep
                )
            )
            return {"deleted": 0, "failed": 0, "total_size_mb": 0}

        deleted_count = 0
        failed_count = 0
        total_bytes = 0

        for filepath in old_files:
            logger.debug(
                Messages.get("SYSTEM.VIDEO_CLEANUP.027.DEBUG", filepath=filepath)
            )

            try:
                file_size = os.path.getsize(filepath)
                age_days = self.get_file_age_days(filepath)

                os.remove(filepath)

                deleted_count += 1
                total_bytes += file_size

                logger.info(
                    Messages.get(
                        "SYSTEM.VIDEO_CLEANUP.028.INFO",
                        age_days=age_days,
                        filename=os.path.basename(filepath),
                        file_size=file_size
                    )
                )

            except Exception:
                failed_count += 1
                logger.exception(
                    Messages.get("SYSTEM.VIDEO_CLEANUP.005.ERROR", video_dir=filepath)
                )

        total_size_mb = round(total_bytes / (1024 * 1024), 2)

        logger.info(
            Messages.get(
                "SYSTEM.VIDEO_CLEANUP.002.INFO",
                deleted=deleted_count,
                failed=failed_count,
                freed_mb=total_size_mb
            )
        )

        return {
            "deleted": deleted_count,
            "failed": failed_count,
            "total_size_mb": total_size_mb
        }

    # ------------------------------------------------------------------
    # Storage Info
    # ------------------------------------------------------------------
    def get_storage_info(self):
        logger.info(
            Messages.get("SYSTEM.VIDEO_CLEANUP.029.INFO", video_dir=self.video_dir)
        )

        if not os.path.exists(self.video_dir):
            logger.warning(
                Messages.get("SYSTEM.VIDEO_CLEANUP.030.WARN", video_dir=self.video_dir)
            )
            return {
                "total_files": 0,
                "total_size_mb": 0,
                "old_files": 0,
                "old_size_mb": 0,
            }

        total_files = 0
        total_bytes = 0
        old_files = 0
        old_bytes = 0

        try:
            for filename in os.listdir(self.video_dir):
                filepath = os.path.join(self.video_dir, filename)

                logger.debug(
                    Messages.get("SYSTEM.VIDEO_CLEANUP.031.DEBUG", filepath=filepath)
                )

                if os.path.isdir(filepath):
                    continue

                size = os.path.getsize(filepath)
                total_bytes += size
                total_files += 1

                if self.is_old_file(filepath):
                    old_files += 1
                    old_bytes += size

        except Exception:
            logger.exception(Messages.get("SYSTEM.VIDEO_CLEANUP.005.ERROR"))

        stats = {
            "total_files": total_files,
            "total_size_mb": round(total_bytes / (1024 * 1024), 2),
            "old_files": old_files,
            "old_size_mb": round(old_bytes / (1024 * 1024), 2),
        }

        logger.debug(
            Messages.get("SYSTEM.VIDEO_CLEANUP.032.DEBUG", stats=stats)
        )
        return stats


# ----------------------------------------------------------------------
# Convenience Wrapper
# ----------------------------------------------------------------------
def cleanup_old_videos(video_dir="/opt/vchanel/fastback/cam1_app_1/detection_videos", days_to_keep=10):
    logger.info(
        Messages.get(
            "SYSTEM.VIDEO_CLEANUP.001.INFO",
            video_dir=video_dir,
            days_to_keep=days_to_keep
        )
    )

    cleaner = VideoCleanup(video_dir, days_to_keep)
    return cleaner.delete_old_videos()


# ----------------------------------------------------------------------
# Standalone Execution
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    video_dir = "/opt/vchanel/fastback/cam1_app_1/detection_videos"
    logging.info(f"🧹 Running standalone cleanup for directory: {video_dir}")

    cleaner = VideoCleanup(video_dir, days_to_keep=10)

    stats_before = cleaner.get_storage_info()
    logging.info(f"📊 BEFORE Cleanup: {stats_before}")

    result = cleaner.delete_old_videos()
    logging.info(f"🧹 Cleanup result: {result}")
