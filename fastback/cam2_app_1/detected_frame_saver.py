# detected_frame_saver.py — Trolley-Window Based Frame Capture
# =============================================================
# Saves ONE annotated frame per trolley trip.
# A new image is captured only when the trolley window has expired
# (same 3-second window used by the trolley count logic).
# ============================================================

from smart_logger import get_logger
logger = get_logger(__name__)

from message_loader import Messages

import cv2
import os
import time

from config_loader import DETECTED_FRAMES_DIR


class DetectedFrameSaver:
    def __init__(self, base_dir=DETECTED_FRAMES_DIR, on_frame_saved=None):
        logger.info(Messages.get("FRAME.SAVER.001.INFO", base_dir=base_dir))

        self.base_dir = base_dir
        self.on_frame_saved = on_frame_saved

        # Per-session state
        # frame_saved        : bool  — was at least one frame saved this session?
        # last_saved_time    : float — epoch time of last saved frame (for window check)
        # trip_count         : int   — how many trolley trips have been captured
        self.frame_saved     = {}   # session_id -> bool
        self.last_saved_time = {}   # session_id -> float
        self.trip_count      = {}   # session_id -> int

        try:
            os.makedirs(base_dir, exist_ok=True)
            logger.debug(Messages.get("FRAME.SAVER.002.DEBUG", base_dir=base_dir))
        except Exception:
            logger.exception(Messages.get("FRAME.SAVER.003.ERROR", base_dir=base_dir))

        logger.info(Messages.get("FRAME.SAVER.004.INFO"))

    # ------------------------------------------------------------------
    # Core: save one frame per trolley trip (window-gated)
    # ------------------------------------------------------------------
    def save_trip_frame(self, session_id: str, frame, label_name: str, trolley_window: float = 3.0):
        """
        Save an annotated frame once per trolley trip.

        A frame is saved when:
          - No frame has ever been saved for this session, OR
          - The trolley window has expired since the last saved frame.

        Args:
            session_id      : Active session identifier
            frame           : Annotated OpenCV frame (BGR)
            label_name      : Class name of the crossing object
            trolley_window  : Seconds between allowed captures (mirrors trolley count window)

        Returns:
            str | None  : Saved file path, or None if skipped / error
        """
        now = time.time()
        last_time = self.last_saved_time.get(session_id)

        logger.debug(
            Messages.get(
                "FRAME.SAVER.005.DEBUG",
                session_id=session_id,
                label_name=label_name,
                saved_before=self.frame_saved.get(session_id, False),
            )
        )

        # Gate: skip if we are still inside the current trolley window
        if last_time is not None and (now - last_time) <= trolley_window:
            logger.debug(
                Messages.get("FRAME.SAVER.015.DEBUG", session_id=session_id)
            )
            return None

        # Window has expired (or first capture) — save the frame
        try:
            trip_num = self.trip_count.get(session_id, 0) + 1

            # Find a free filename:  <session_id>_trip<N>.jpg
            for i in range(1, 2000):
                filename = f"{session_id}_trip{trip_num}_{i}.jpg"
                frame_path = os.path.join(self.base_dir, filename)
                if not os.path.exists(frame_path):
                    break
            else:
                logger.error(Messages.get("FRAME.SAVER.006.ERROR", session_id=session_id))
                return None

            logger.debug(Messages.get("FRAME.SAVER.007.DEBUG", frame_path=frame_path))

            success = cv2.imwrite(frame_path, frame)

            if success:
                # Update state
                self.frame_saved[session_id]     = True
                self.last_saved_time[session_id] = now
                self.trip_count[session_id]      = trip_num

                logger.info(
                    Messages.get(
                        "FRAME.SAVER.008.INFO",
                        session_id=session_id,
                        filename=filename,
                        label_name=label_name,
                    )
                )

                # Fire callback (e.g. update session image_path in SessionManager)
                try:
                    if self.on_frame_saved:
                        logger.debug(
                            Messages.get(
                                "FRAME.SAVER.009.DEBUG",
                                session_id=session_id,
                                frame_path=frame_path,
                            )
                        )
                        self.on_frame_saved(session_id, frame_path)
                except Exception:
                    logger.exception(
                        Messages.get("FRAME.SAVER.010.ERROR", session_id=session_id)
                    )

                return frame_path

            else:
                logger.error(
                    Messages.get(
                        "FRAME.SAVER.011.ERROR",
                        session_id=session_id,
                        frame_path=frame_path,
                    )
                )
                return None

        except Exception:
            logger.exception(Messages.get("FRAME.SAVER.012.ERROR", session_id=session_id))
            return None

    # ------------------------------------------------------------------
    # Backwards-compat alias (old name used in session.py callback path)
    # ------------------------------------------------------------------
    def save_counted_frame(self, session_id: str, frame, label_name: str, trolley_window: float = 3.0):
        """Alias for save_trip_frame — keeps old call-sites working."""
        return self.save_trip_frame(session_id, frame, label_name, trolley_window)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def has_saved_frame(self, session_id: str) -> bool:
        saved_state = self.frame_saved.get(session_id, False)
        logger.debug(
            Messages.get(
                "FRAME.SAVER.013.DEBUG",
                session_id=session_id,
                saved_state=saved_state,
            )
        )
        return saved_state

    def get_trip_count(self, session_id: str) -> int:
        """Returns how many trip images have been captured for this session."""
        return self.trip_count.get(session_id, 0)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup_session(self, session_id: str):
        logger.info(Messages.get("FRAME.SAVER.014.INFO", session_id=session_id))

        try:
            had_entry = session_id in self.frame_saved

            if had_entry:
                trips = self.trip_count.get(session_id, 0)
                logger.debug(
                    Messages.get(
                        "FRAME.SAVER.015.DEBUG",
                        session_id=session_id,
                        saved_flag=self.frame_saved[session_id],
                    )
                )
                logger.info(
                    Messages.get(
                        "FRAME.SAVER.TRIP.001.INFO",
                        session_id=session_id,
                        trips=trips,
                    )
                )
                del self.frame_saved[session_id]
                self.last_saved_time.pop(session_id, None)
                self.trip_count.pop(session_id, None)
            else:
                logger.debug(
                    Messages.get("FRAME.SAVER.016.DEBUG", session_id=session_id)
                )

        except Exception:
            logger.exception(
                Messages.get("FRAME.SAVER.017.ERROR", session_id=session_id)
            )

        logger.info(Messages.get("FRAME.SAVER.018.INFO", session_id=session_id))