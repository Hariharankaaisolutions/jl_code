"""
cam1/detection/tracker.py — ByteTrack Counter
===============================================
Tracks objects across frames using ByteTrack.
Counts objects crossing CROSS_LINE_X with confidence voting.
Max 100 lines. One responsibility: track and count.
"""

from collections import defaultdict
from typing import Optional

import numpy as np
import supervision as sv

from core.config import get, getint, getfloat, getmap, getbool
from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("TRACK")

CROSS_LINE_X  = getint("CAM1_CROSS_LINE_X",   200)
CROSS_DIR     = get("CAM1_CROSS_DIRECTION",    "left")
BOX_CLASSES   = getmap("CAM1_BOX_CLASSES")
BALE_CLASSES  = getmap("CAM1_BALE_CLASSES")
BT_ACTIVATION = getfloat("BYTETRACK_ACTIVATION_THRESHOLD", 0.5)
BT_BUFFER     = getint("BYTETRACK_LOST_TRACK_BUFFER",       60)
BT_MATCHING   = getfloat("BYTETRACK_MATCHING_THRESHOLD",    0.7)

CLASS_NAMES = {
    0: "box-Sedr", 1: "bale",    2: "box",
    3: "fbale",    4: "sbale",   5: "tbale_a", 6: "tbale_b",
}


def _counter(cls_name: str) -> Optional[str]:
    if cls_name in BOX_CLASSES:
        return "box"
    if cls_name in BALE_CLASSES:
        return "bale"
    return None


def _weight(cls_name: str) -> int:
    return BOX_CLASSES.get(cls_name, BALE_CLASSES.get(cls_name, 1))


class ByteTrackCounter:
    """Tracks objects and counts line crossings using ByteTrack."""

    def __init__(self):
        self.tracker    = sv.ByteTrack(
            track_activation_threshold=BT_ACTIVATION,
            lost_track_buffer=BT_BUFFER,
            minimum_matching_threshold=BT_MATCHING,
        )
        self.prev_x:     dict[int, int]              = {}
        self.counted:    set[int]                    = set()
        self.votes:      dict                        = defaultdict(lambda: defaultdict(float))
        self.counts:     dict[str, int]              = {
            "box": 0, "bale": 0, "trolley": 0, "bag": 0}
        logger.info(LOG("TRACK.001.INFO",
            activation=BT_ACTIVATION, buffer=BT_BUFFER))

    def update(self, detections: list[dict]) -> sv.Detections:
        """Update tracker with new detections. Returns tracked sv.Detections."""
        if detections:
            xyxy  = np.array([[d["x1"],d["y1"],d["x2"],d["y2"]]
                              for d in detections], dtype=np.float32)
            conf  = np.array([d["conf"]   for d in detections], dtype=np.float32)
            cls   = np.array([d["cls_id"] for d in detections], dtype=int)
            sv_d  = sv.Detections(xyxy=xyxy, confidence=conf, class_id=cls)
        else:
            sv_d  = sv.Detections.empty()

        return self.tracker.update_with_detections(sv_d)

    def accumulate_votes(self, tracked: sv.Detections) -> None:
        """Accumulate confidence votes per track per class."""
        if tracked.tracker_id is None:
            return
        for tid, cid, conf in zip(
            tracked.tracker_id, tracked.class_id, tracked.confidence
        ):
            if tid is None:
                continue
            cls_name = CLASS_NAMES.get(int(cid), "unknown")
            if _counter(cls_name):
                self.votes[tid][cls_name] += float(conf)

    def check_crossings(self, tracked: sv.Detections) -> dict:
        """Check line crossings. Returns new counts this frame."""
        new = {"box": 0, "bale": 0, "trolley": 0, "bag": 0}
        if tracked.tracker_id is None:
            return new
        for xyxy, tid in zip(tracked.xyxy, tracked.tracker_id):
            if tid is None:
                continue
            cx = int((xyxy[0] + xyxy[2]) / 2)
            if tid in self.prev_x:
                old_cx = self.prev_x[tid]
                crossed = (old_cx > CROSS_LINE_X >= cx
                           if CROSS_DIR == "left"
                           else old_cx < CROSS_LINE_X <= cx)
                if crossed and tid not in self.counted:
                    votes    = self.votes.get(tid, {})
                    best_cls = max(votes, key=votes.get) if votes else None
                    if best_cls and _counter(best_cls):
                        counter = _counter(best_cls)
                        weight  = _weight(best_cls)
                        self.counts[counter]  += weight
                        new[counter]          += weight
                        self.counted.add(tid)
                        logger.info(LOG("TRACK.003.INFO",
                            cls=best_cls, old_cx=old_cx,
                            cx=cx, total=self.counts[counter]))
                        logger.info(LOG("TRACK.004.INFO",
                            cls=best_cls, weight=weight,
                            counter=counter,
                            total=self.counts[counter]))
            self.prev_x[tid] = cx
        return new

    def reset(self) -> None:
        """Reset tracker for new session."""
        self.tracker  = sv.ByteTrack(
            track_activation_threshold=BT_ACTIVATION,
            lost_track_buffer=BT_BUFFER,
            minimum_matching_threshold=BT_MATCHING,
        )
        self.prev_x   = {}
        self.counted  = set()
        self.votes    = defaultdict(lambda: defaultdict(float))
        self.counts   = {"box": 0, "bale": 0, "trolley": 0, "bag": 0}
