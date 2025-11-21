# detected_frame_saver.py — Converted to Message Codes (FRAME.SAVER.*)
# ====================================================================

from smart_logger import get_logger
logger = get_logger(__name__)

from message_loader import Messages   # <-- NEW

import cv2
import os
from datetime import datetime

from config_loader import DETECTED_FRAMES_DIR


class DetectedFrameSaver:
    def __init__(self, base_dir=DETECTED_FRAMES_DIR, on_frame_saved=None):
        logger.info(Messages.get("FRAME.SAVER.001.INFO", base_dir=base_dir))

        self.base_dir = base_dir
        self.frame_saved = {}              # session_id -> bool
        self.on_frame_saved = on_frame_saved

        try:
            os.makedirs(base_dir, exist_ok=True)
            logger.debug(Messages.get("FRAME.SAVER.002.DEBUG", base_dir=base_dir))
        except Exception:
            logger.exception(Messages.get("FRAME.SAVER.003.ERROR", base_dir=base_dir))

        logger.info(Messages.get("FRAME.SAVER.004.INFO"))

    # ----------------------------------------------------------------------
    # Save the FIRST counted frame only
    # ----------------------------------------------------------------------
    def save_counted_frame(self, session_id, frame, label_name):
        logger.debug(
            Messages.get(
                "FRAME.SAVER.005.DEBUG",
                session_id=session_id,
                label_name=label_name,
                saved_before=self.frame_saved.get(session_id)
            )
        )

        # If already saved → skip
        if self.frame_saved.get(session_id, False):
            logger.debug(Messages.get("FRAME.SAVER.015.DEBUG", session_id=session_id))
            return None

        try:
            # Find a free filename
            for i in range(1, 2000):
                filename = f"{session_id}_{i}.jpg"
                frame_path = os.path.join(self.base_dir, filename)
                if not os.path.exists(frame_path):
                    break
            else:
                logger.error(Messages.get("FRAME.SAVER.006.ERROR", session_id=session_id))
                return None

            logger.debug(Messages.get("FRAME.SAVER.007.DEBUG", frame_path=frame_path))

            # Save file
            success = cv2.imwrite(frame_path, frame)

            if success:
                self.frame_saved[session_id] = True
                logger.info(
                    Messages.get(
                        "FRAME.SAVER.008.INFO",
                        session_id=session_id,
                        filename=filename,
                        label_name=label_name
                    )
                )

                # Callback
                try:
                    if self.on_frame_saved:
                        logger.debug(
                            Messages.get(
                                "FRAME.SAVER.009.DEBUG",
                                session_id=session_id,
                                frame_path=frame_path
                            )
                        )
                        self.on_frame_saved(session_id, frame_path)
                except Exception:
                    logger.exception(Messages.get("FRAME.SAVER.010.ERROR", session_id=session_id))

                return frame_path

            else:
                logger.error(
                    Messages.get(
                        "FRAME.SAVER.011.ERROR",
                        session_id=session_id,
                        frame_path=frame_path
                    )
                )
                return None

        except Exception:
            logger.exception(Messages.get("FRAME.SAVER.012.ERROR", session_id=session_id))
            return None

    # ----------------------------------------------------------------------
    # Check if a frame was saved
    # ----------------------------------------------------------------------
    def has_saved_frame(self, session_id):
        saved_state = self.frame_saved.get(session_id, False)
        logger.debug(
            Messages.get(
                "FRAME.SAVER.013.DEBUG",
                session_id=session_id,
                saved_state=saved_state
            )
        )
        return saved_state

    # ----------------------------------------------------------------------
    # Cleanup session
    # ----------------------------------------------------------------------
    def cleanup_session(self, session_id):
        logger.info(Messages.get("FRAME.SAVER.014.INFO", session_id=session_id))

        try:
            if session_id in self.frame_saved:
                logger.debug(
                    Messages.get(
                        "FRAME.SAVER.015.DEBUG",
                        session_id=session_id,
                        saved_flag=self.frame_saved[session_id]
                    )
                )
                del self.frame_saved[session_id]
            else:
                logger.debug(Messages.get("FRAME.SAVER.016.DEBUG", session_id=session_id))
        except Exception:
            logger.exception(Messages.get("FRAME.SAVER.017.ERROR", session_id=session_id))

        logger.info(Messages.get("FRAME.SAVER.018.INFO", session_id=session_id))
