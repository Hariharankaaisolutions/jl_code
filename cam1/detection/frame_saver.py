"""
cam1/detection/frame_saver.py — Frame Saver
=============================================
Saves detected frames (trip images) and RL frames.
Detected frames shown in dashboard.
RL frames used for model improvement.
Max 80 lines. One responsibility: save frames.
"""

import os
import cv2
import json
import time
from datetime import datetime
from pathlib import Path

from core.config import get, getfloat, getint
from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("FRAME")

FRAMES_DIR  = get("DETECTED_FRAMES_DIR",
                  "/opt/secure_ai/database/detected_frames")
RL_DIR      = get("RL_SAVE_DIR", "/opt/secure_ai/reinforcement_learning")
RL_CONF     = getfloat("RL_CONF_THRESHOLD",   0.9)
RL_PROX     = getint("RL_LINE_PROXIMITY_PX",  50)
CROSS_LINE  = getint("CAM1_CROSS_LINE_X",     200)

os.makedirs(FRAMES_DIR, exist_ok=True)


class FrameSaver:
    """Saves detected frames and RL frames per session."""

    def __init__(self, session_id: str, transaction_id: str):
        self.session_id     = session_id
        self.transaction_id = transaction_id
        self.trip_count     = 0
        self.last_save_time = 0.0
        self.image_paths:   list[str] = []

    def save_detected_frame(self, frame, trolley_window: float = 3.0,
                             tracked=None, counts: dict = None) -> str:
        """Save annotated frame when object crosses line. One per trolley window."""
        now = time.time()
        if now - self.last_save_time < trolley_window:
            logger.debug(LOG("FRAME.005.DEBUG"))
            return None
        try:
            self.trip_count    += 1
            filename            = f"{self.session_id}_trip{self.trip_count}_1.jpg"
            path                = os.path.join(FRAMES_DIR, filename)
            annotated           = self._annotate(frame.copy(), tracked, counts)
            cv2.imwrite(path, annotated)
            self.last_save_time = now
            self.image_paths.append(path)
            logger.info(LOG("FRAME.001.INFO",
                session_id=self.session_id[:8],
                path=path, trip=self.trip_count))
            return path
        except Exception as e:
            logger.error(LOG("FRAME.002.ERROR",
                session_id=self.session_id[:8], error=e))
            return None

    def save_rl_frame(self, frame, label: str, conf: float) -> None:
        """Save low-confidence frame near line for RL review."""
        try:
            date_str  = datetime.now().strftime("%Y-%m-%d")
            ts        = datetime.now().strftime("%H%M%S_%f")
            save_dir  = os.path.join(
                RL_DIR, "cam1", date_str, self.transaction_id)
            os.makedirs(save_dir, exist_ok=True)
            filename  = f"{self.transaction_id}_{ts}.jpg"
            path      = os.path.join(save_dir, filename)
            frame_cp  = frame.copy()
            cv2.putText(frame_cp, f"{label} {conf:.3f}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (0, 0, 255), 2, cv2.LINE_AA)
            cv2.imwrite(path, frame_cp)
            logger.info(LOG("FRAME.003.INFO",
                session_id=self.session_id[:8],
                label=label, conf=round(conf, 3)))
        except Exception as e:
            logger.error(LOG("FRAME.004.ERROR", error=e))

    def check_rl_frame(self, frame, detections: list, tracked) -> None:
        """Check if any detection near line with low confidence."""
        if tracked.tracker_id is None:
            return
        for xyxy, cid, conf in zip(
            tracked.xyxy, tracked.class_id, tracked.confidence
        ):
            cx = int((xyxy[0] + xyxy[2]) / 2)
            if abs(cx - CROSS_LINE) <= RL_PROX and conf < RL_CONF:
                from cam1.detection.yolox import CLASS_NAMES
                label = CLASS_NAMES.get(int(cid), "unknown")
                self.save_rl_frame(frame, label, float(conf))

    def get_image_paths_json(self) -> str:
        """Return JSON string of all saved image paths."""
        return json.dumps(self.image_paths) if self.image_paths else None

    def _annotate(self, frame, tracked=None, counts: dict = None) -> 'np.ndarray':
        """Draw bounding boxes, labels and count line on frame."""
        import numpy as np
        # Draw count line
        cv2.line(frame, (CROSS_LINE, 0), (CROSS_LINE, frame.shape[0]),
                 (0, 255, 0), 2)
        cv2.putText(frame, "COUNT LINE", (CROSS_LINE + 5, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        # Draw tracked boxes
        if tracked is not None and tracked.tracker_id is not None:
            for xyxy, tid, cid, conf in zip(
                tracked.xyxy, tracked.tracker_id,
                tracked.class_id, tracked.confidence
            ):
                x1, y1, x2, y2 = map(int, xyxy)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
                from cam1.detection.yolox import CLASS_NAMES
                label = CLASS_NAMES.get(int(cid), "unknown")
                cv2.putText(frame, f"{label} {conf:.2f}",
                    (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1)
        # Draw counts
        if counts:
            y = 30
            for cls, cnt in counts.items():
                if cnt > 0:
                    cv2.putText(frame, f"{cls}: {cnt}",
                        (10, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 0, 255), 2)
                    y += 25
        return frame

    def cleanup(self) -> None:
        logger.info(LOG("FRAME.006.INFO",
            session_id=self.session_id[:8],
            trips=self.trip_count))
