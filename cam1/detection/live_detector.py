"""
cam1/detection/live_detector.py — Live Detection Pipeline
===========================================================
Orchestrates full live detection pipeline:
Frame → MOG2 → YOLOX → ByteTrack → Count → Save → DB
Max 120 lines. One responsibility: run detection pipeline.
"""

import cv2
import threading
from datetime import datetime
from typing import Callable, Optional

from core.config import get, getint
from core.logger import get_logger
from core.log_codes import get as LOG
from core.db_transaction import update_counts
from core.db_daily_counts import upsert
from core.mqtt import publish_counts
from cam1.detection.mog2 import MOG2Filter
from cam1.detection.yolox import infer, CLASS_NAMES
from cam1.detection.tracker import ByteTrackCounter
from cam1.detection.frame_saver import FrameSaver
from cam1.recording.video_writer import DetectedVideoWriter

logger = get_logger("DET")

CROSS_LINE  = getint("CAM1_CROSS_LINE_X", 200)
W           = getint("CAM1_FRAME_WIDTH",  640)
H           = getint("CAM1_FRAME_HEIGHT", 640)


class LiveDetector:
    """Full live detection pipeline for cam1."""

    def __init__(
        self,
        session_id:     str,
        transaction_id: str,
        cam:            str = "cam_1",
        on_count:       Optional[Callable] = None,
    ):
        self.session_id     = session_id
        self.transaction_id = transaction_id
        self.cam            = cam
        self.on_count       = on_count
        self._stop          = threading.Event()
        self._thread:       Optional[threading.Thread] = None
        self.frame_count    = 0
        self.motion_count   = 0
        self.mog2           = None
        self.tracker        = ByteTrackCounter()
        self.frame_saver    = FrameSaver(session_id, transaction_id)
        self.video_writer   = DetectedVideoWriter(transaction_id)
        logger.info(LOG("DET.001.INFO",
            cam=cam, source=get("CAM1_RTMP_INPUT")))

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"detector_{self.session_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        logger.info(LOG("DET.002.INFO"))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
        self.video_writer.close()
        logger.info(LOG("DET.004.INFO",
            frames=self.frame_count, motion=self.motion_count))

    def get_counts(self) -> dict:
        return dict(self.tracker.counts)

    def _run(self) -> None:
        source = get("CAM1_RTMP_INPUT", "rtmp://localhost/live/cam_1")
        cap    = cv2.VideoCapture(source, cv2.CAP_FFMPEG)

        if not cap.isOpened():
            logger.error(LOG("DET.008.ERROR", source=source))
            return

        fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or W
        fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or H
        logger.info(LOG("DET.007.INFO",
            fps=cap.get(cv2.CAP_PROP_FPS), width=fw, height=fh))

        self.mog2 = MOG2Filter(fw, fh)
        fail_count = 0

        while not self._stop.is_set():
            ret, frame = cap.read()
            if not ret or frame is None:
                fail_count += 1
                if fail_count >= 30:
                    logger.warning(LOG("DET.006.WARN",
                        frame_num=self.frame_count, count=fail_count))
                    break
                continue

            fail_count = 0
            self.frame_count += 1

            if frame.shape[1] != fw or frame.shape[0] != fh:
                frame = cv2.resize(frame, (fw, fh))

            # MOG2 motion check
            has_motion, fg = self.mog2.has_motion(frame)
            if not has_motion:
                continue

            self.motion_count += 1

            # YOLOX inference
            try:
                detections = infer(frame)
            except Exception as e:
                logger.error(LOG("DET.005.ERROR", error=e))
                continue

            # ByteTrack update
            tracked = self.tracker.update(detections)
            self.tracker.accumulate_votes(tracked)
            new_counts = self.tracker.check_crossings(tracked)

            # Save detected frame on crossing
            if any(v > 0 for v in new_counts.values()):
                self.frame_saver.save_detected_frame(frame)
                self._update_db()
                if self.on_count:
                    try:
                        self.on_count(self.session_id,
                                      self.tracker.counts.copy())
                    except Exception:
                        pass

            # Check RL frames
            self.frame_saver.check_rl_frame(frame, detections, tracked)

            # Annotate and save to detected video
            self._annotate(frame, tracked)
            self.video_writer.write(frame)

        cap.release()

    def _update_db(self) -> None:
        counts = self.tracker.counts
        update_counts(
            transaction_id=self.transaction_id,
            box_count=counts.get("box", 0),
            bale_count=counts.get("bale", 0),
            bag_count=counts.get("bag", 0),
            trolley_count=counts.get("trolley", 0),
            image_path=self.frame_saver.get_image_paths_json(),
        )
        upsert(
            session_id=self.session_id,
            transaction_id=self.transaction_id,
            cam=self.cam,
            box_count=counts.get("box", 0),
            bale_count=counts.get("bale", 0),
            trolley_count=counts.get("trolley", 0),
            bag_count=counts.get("bag", 0),
        )
        publish_counts(self.session_id, self.transaction_id, counts)

    def _annotate(self, frame, tracked) -> None:
        cv2.line(frame, (CROSS_LINE, 0), (CROSS_LINE, frame.shape[0]),
                 (0, 255, 0), 2)
        self.mog2.draw_zones(frame)
        y = 25
        for cls, cnt in self.tracker.counts.items():
            cv2.putText(frame, f"{cls}:{cnt}", (10, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            y += 25
