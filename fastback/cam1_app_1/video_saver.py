# video_saver.py — Converted to Message Codes (VIDEO.SAVER.*)
# ===========================================================

from smart_logger import get_logger
logger = get_logger(__name__)

from message_loader import Messages   # <-- NEW

import cv2
import os
from datetime import datetime

from config_loader import VIDEO_SAVE_DIR


class VideoSaver:
    def __init__(self, base_dir=VIDEO_SAVE_DIR):
        logger.info(Messages.get("VIDEO.SAVER.001.INFO", base_dir=base_dir))

        self.base_dir = base_dir
        self.active_writers = {}  
        self.video_paths = {}     

        try:
            os.makedirs(base_dir, exist_ok=True)
            logger.debug(Messages.get("VIDEO.SAVER.002.DEBUG", base_dir=base_dir))
        except Exception:
            logger.exception(Messages.get("VIDEO.SAVER.003.ERROR", base_dir=base_dir))

        logger.info(Messages.get("VIDEO.SAVER.004.INFO"))

    # ------------------------------------------------------------------
    # Generate Next Filename
    # ------------------------------------------------------------------
    def _get_next_filename(self, session_id, extension):
        logger.debug(
            Messages.get(
                "VIDEO.SAVER.005.DEBUG",
                session_id=session_id,
                extension=extension
            )
        )

        counter = 1
        try:
            while True:
                filename = f"{session_id}_{counter}{extension}"
                filepath = os.path.join(self.base_dir, filename)

                if not os.path.exists(filepath):
                    logger.debug(Messages.get("VIDEO.SAVER.006.DEBUG", filename=filepath))
                    return filepath

                counter += 1

        except Exception:
            logger.exception(Messages.get("VIDEO.SAVER.007.ERROR", session_id=session_id))
            return os.path.join(self.base_dir, f"{session_id}_fallback{extension}")

    # ------------------------------------------------------------------
    # Start Recording
    # ------------------------------------------------------------------
    def start_recording(self, session_id, frame_width=640, frame_height=480, fps=20):
        logger.info(
            Messages.get(
                "VIDEO.SAVER.008.INFO",
                session_id=session_id,
                width=frame_width,
                height=frame_height,
                fps=fps
            )
        )

        if session_id in self.active_writers:
            logger.warning(Messages.get("VIDEO.SAVER.009.WARN", session_id=session_id))
            return self.video_paths[session_id]

        # next filename
        video_path = self._get_next_filename(session_id, ".mp4")

        try:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(video_path, fourcc, fps, (frame_width, frame_height))
        except Exception:
            logger.exception(Messages.get("VIDEO.SAVER.010.ERROR", session_id=session_id))
            return None

        if not writer.isOpened():
            logger.error(Messages.get("VIDEO.SAVER.011.ERROR", session_id=session_id, video_path=video_path))
            return None

        self.active_writers[session_id] = writer
        self.video_paths[session_id] = video_path

        logger.info(Messages.get("VIDEO.SAVER.012.INFO", session_id=session_id, video_path=video_path))
        return video_path

    # ------------------------------------------------------------------
    # Write Frame
    # ------------------------------------------------------------------
    def write_frame(self, session_id, frame):
        logger.debug(Messages.get("VIDEO.SAVER.013.DEBUG", session_id=session_id))

        if session_id not in self.active_writers:
            logger.warning(Messages.get("VIDEO.SAVER.014.WARN", session_id=session_id))
            return False

        try:
            self.active_writers[session_id].write(frame)
            logger.debug(Messages.get("VIDEO.SAVER.015.DEBUG", session_id=session_id))
            return True
        except Exception:
            logger.exception(Messages.get("VIDEO.SAVER.016.ERROR", session_id=session_id))
            return False

    # ------------------------------------------------------------------
    # Save First Frame
    # ------------------------------------------------------------------
    def save_first_frame(self, session_id, frame):
        logger.info(Messages.get("VIDEO.SAVER.017.INFO", session_id=session_id))

        frame_path = self._get_next_filename(session_id, ".jpg")

        try:
            success = cv2.imwrite(frame_path, frame)
            if success:
                logger.info(Messages.get("VIDEO.SAVER.018.INFO", session_id=session_id, frame_path=frame_path))
                return frame_path
            else:
                logger.error(Messages.get("VIDEO.SAVER.019.ERROR", session_id=session_id))
                return None
        except Exception:
            logger.exception(Messages.get("VIDEO.SAVER.020.ERROR", session_id=session_id))
            return None

    # ------------------------------------------------------------------
    # Stop Recording
    # ------------------------------------------------------------------
    def stop_recording(self, session_id):
        logger.info(Messages.get("VIDEO.SAVER.021.INFO", session_id=session_id))

        if session_id not in self.active_writers:
            logger.warning(Messages.get("VIDEO.SAVER.022.WARN", session_id=session_id))
            return None

        try:
            self.active_writers[session_id].release()
            logger.debug(Messages.get("VIDEO.SAVER.023.DEBUG", session_id=session_id))
        except Exception:
            logger.exception(Messages.get("VIDEO.SAVER.024.ERROR", session_id=session_id))

        video_path = self.video_paths.get(session_id)

        try:
            del self.active_writers[session_id]
            del self.video_paths[session_id]
        except Exception:
            logger.exception(Messages.get("VIDEO.SAVER.025.ERROR", session_id=session_id))

        logger.info(Messages.get("VIDEO.SAVER.026.INFO", session_id=session_id, video_path=video_path))
        return video_path

    # ------------------------------------------------------------------
    # Check Recording
    # ------------------------------------------------------------------
    def is_recording(self, session_id):
        recording = session_id in self.active_writers
        logger.debug(Messages.get("VIDEO.SAVER.027.DEBUG", session_id=session_id, recording=recording))
        return recording

    # ------------------------------------------------------------------
    # Cleanup All Sessions
    # ------------------------------------------------------------------
    def cleanup_all(self):
        logger.info(Messages.get("VIDEO.SAVER.028.INFO"))

        for session_id in list(self.active_writers.keys()):
            try:
                self.stop_recording(session_id)
            except Exception:
                logger.exception(Messages.get("VIDEO.SAVER.029.ERROR", session_id=session_id))

        logger.info(Messages.get("VIDEO.SAVER.030.INFO"))
