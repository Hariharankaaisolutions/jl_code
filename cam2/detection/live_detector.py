"""
cam1/detection/live_detector.py — Live Detection Pipeline
===========================================================
Exactly mirrors old main_detection.py logic:
- Grayscale mode: BGR→gray→3ch
- supervision BoxAnnotator + LabelAnnotator
- Confidence voting per track
- White count line thickness=3
- Count bar bottom-left
- fuse_model for speed
- RL frame saving
"""

import cv2
import sys
import time
import threading
import torch
import numpy as np
from datetime import datetime
from collections import defaultdict
from typing import Callable, Optional
from pathlib import Path

import supervision as sv
from yolox.utils import fuse_model, postprocess
from yolox.data.data_augment import ValTransform

from core.config import get, getint, getfloat, getbool
from core.logger import get_logger
from core.log_codes import get as LOG
from core.db_transaction import update_counts
from core.db_daily_counts import upsert
from core.mqtt import publish_counts
from cam2.detection.frame_saver import FrameSaver
from cam2.recording.video_writer import DetectedVideoWriter

logger = get_logger("DET")

# ── Config ─────────────────────────────────────────────────────
BASE        = Path("/opt/secure_ai")
MODEL_PATH  = str(BASE / get("CAM2_MODEL",    "cam2/models/jl_yolox_cam1.pth"))
EXP_FILE    = str(BASE / get("CAM2_EXP_FILE", "cam2/YOLOX/exps/default/yolox_s.py"))
NUM_CLASS   = getint("CAM2_NUM_CLASSES",  7)
CONF_THRES  = getfloat("CAM2_CONF_THRES", 0.4)
IOU_THRES   = getfloat("CAM2_IOU_THRES",  0.45)
CROSS_LINE  = getint("CAM2_CROSS_LINE_X", 200)
CROSS_DIR      = get("CAM2_CROSS_DIRECTION",  "left")
INFERENCE_MODE = get("CAM2_INFERENCE_MODE", "rgb")
W              = getint("CAM2_FRAME_WIDTH",  640)
H              = getint("CAM2_FRAME_HEIGHT", 640)
RL_ENABLED     = getbool("RL_ENABLED",       True)
RL_DIR         = get("RL_SAVE_DIR", "/opt/secure_ai/reinforcement_learning")
RL_CONF        = getfloat("RL_CONF_THRESHOLD",  0.9)
RL_PROX        = getint("RL_LINE_PROXIMITY_PX", 50)
SOURCE      = get("CAM2_RTMP_INPUT", "rtmp://localhost/live/cam_1")

# Load CLASS_NAMES from master.properties
def _load_class_names(key: str) -> dict:
    raw = get(key, "")
    result = {}
    for item in raw.split(","):
        if ":" in item:
            idx, name = item.split(":", 1)
            result[int(idx.strip())] = name.strip()
    return result

CLASS_NAMES = _load_class_names("CAM2_CLASS_NAMES")

from core.config import getmap
BAG_CLASSES   = getmap("CAM2_BAG_CLASSES")
CLASS_WEIGHTS = {k: 1 for k in BAG_CLASSES}

# ── YOLOX Singleton ────────────────────────────────────────────
_model  = None
_exp    = None
_device = None
_lock   = threading.Lock()


def _load_model():
    global _model, _exp, _device
    if _model is not None:
        return _model, _exp, _device
    with _lock:
        if _model is not None:
            return _model, _exp, _device
        yolox_path = str(BASE / "cam2" / "YOLOX")
        if yolox_path not in sys.path:
            sys.path.insert(0, yolox_path)
        import importlib.util
        spec = importlib.util.spec_from_file_location("yolox_exp", EXP_FILE)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        exp             = mod.Exp()
        exp.num_classes = NUM_CLASS
        exp.test_conf   = CONF_THRES
        exp.nmsthre     = IOU_THRES
        exp.test_size   = (W, H)
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        logger.info(LOG("YOLOX.001.INFO", path=MODEL_PATH, device=device))
        ckpt  = torch.load(MODEL_PATH, map_location=device, weights_only=False)
        model = exp.get_model().to(device)
        model.eval()
        model.load_state_dict(ckpt.get("model", ckpt))
        model = fuse_model(model)
        if device == "cuda:0":
            model = model.half()
        _model, _exp, _device = model, exp, device
        logger.info(LOG("YOLOX.002.INFO", device=device, classes=NUM_CLASS))
        return _model, _exp, _device


def _infer(model, exp, device, frame_bgr) -> sv.Detections:
    """BGR frame → grayscale 3ch → YOLOX → sv.Detections"""
    gray    = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    frame3  = cv2.merge([gray, gray, gray])
    preproc = ValTransform(legacy=False)
    img, _  = preproc(frame3, None, exp.test_size)
    h, w    = frame3.shape[:2]
    ratio   = min(exp.test_size[0]/h, exp.test_size[1]/w)
    tensor  = torch.from_numpy(img).unsqueeze(0).to(device)
    tensor  = tensor.half() if device == "cuda:0" else tensor.float()
    with torch.no_grad():
        out = model(tensor)
        out = postprocess(out, exp.num_classes, exp.test_conf, exp.nmsthre)
    if out[0] is None:
        return sv.Detections.empty()
    dets = out[0].cpu().numpy()
    dets[:, 0:4] /= ratio
    return sv.Detections(
        xyxy       = dets[:, :4],
        confidence = dets[:, 4] * dets[:, 5],
        class_id   = dets[:, 6].astype(int),
    )


def _save_rl_frame(frame, session_id, transaction_id, label, conf):
    try:
        date_str  = datetime.now().strftime("%Y-%m-%d")
        ts        = datetime.now().strftime("%H%M%S_%f")
        save_dir  = os.path.join(RL_DIR, "cam1", date_str, transaction_id)
        os.makedirs(save_dir, exist_ok=True)
        path      = os.path.join(save_dir, f"{transaction_id}_{ts}.jpg")
        frame_cp  = frame.copy()
        cv2.putText(frame_cp, f"{label} {conf:.3f}",
            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.imwrite(path, frame_cp)
        logger.info(LOG("FRAME.003.INFO",
            session_id=session_id[:8], label=label, conf=round(conf, 3)))
    except Exception as e:
        logger.error(LOG("FRAME.004.ERROR", error=e))


import os


class LiveDetector:
    """Full live detection pipeline — exactly mirrors old main_detection.py"""

    def __init__(self, session_id, transaction_id, cam="cam_1",
                 on_count: Optional[Callable] = None):
        self.session_id     = session_id
        self.transaction_id = transaction_id
        self.cam            = cam
        self.on_count       = on_count
        self._stop          = threading.Event()
        self._thread        = None
        self.frame_count    = 0
        self.motion_count   = 0
        self.counts         = {"bag": 0, "trolley": 0}
        self.frame_saver    = FrameSaver(session_id, transaction_id)
        self.video_writer   = DetectedVideoWriter(transaction_id)
        self._last_trolley  = 0.0
        self._trolley_win   = 3.0
        logger.info(LOG("DET.001.INFO", cam=cam, source=SOURCE))

    def start(self):
        self._thread = threading.Thread(
            target=self._run, daemon=True,
            name=f"detector_{self.session_id[:8]}")
        self._thread.start()
        logger.info(LOG("DET.002.INFO"))

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
        self.video_writer.close()
        logger.info(LOG("DET.004.INFO",
            frames=self.frame_count, motion=self.motion_count))

    def get_counts(self) -> dict:
        return dict(self.counts)

    def _run(self):
        model, exp, device = _load_model()
        cap = cv2.VideoCapture(SOURCE, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            logger.error(LOG("DET.008.ERROR", source=SOURCE))
            return

        fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or W
        fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or H
        logger.info(LOG("DET.007.INFO",
            fps=cap.get(cv2.CAP_PROP_FPS), width=fw, height=fh))

        # Supervision annotators — exactly like old system
        box_annotator   = sv.BoundingBoxAnnotator(thickness=3)
        label_annotator = sv.LabelAnnotator(text_scale=0.6, text_thickness=2)

        tracker          = sv.ByteTrack(
            track_activation_threshold=0.5,
            lost_track_buffer=60,
            minimum_matching_threshold=0.7,
        )
        prev_x           = {}
        counted_ids      = set()
        track_class_votes = defaultdict(lambda: defaultdict(float))

        def get_best_class(tid):
            votes = track_class_votes.get(tid)
            if not votes:
                return None
            return max(votes, key=votes.get)

        fail_count = 0

        while not self._stop.is_set():
            ret, frame = cap.read()
            if not ret or frame is None:
                fail_count += 1
                if fail_count >= 30:
                    logger.warning(LOG("DET.006.WARN",
                        frame_num=self.frame_count, count=fail_count))
                    cap.release()
                    import time as _time
                    _time.sleep(3)
                    cap = cv2.VideoCapture(SOURCE, cv2.CAP_FFMPEG)
                    fail_count = 0
                continue

            fail_count = 0
            self.frame_count += 1

            if frame.shape[1] != fw or frame.shape[0] != fh:
                frame = cv2.resize(frame, (fw, fh))

            color_frame = frame.copy()

            # ── YOLOX inference (grayscale 3ch) ───────────────────────────
            try:
                detections = _infer(model, exp, device, color_frame)
            except Exception as e:
                logger.error(LOG("DET.005.ERROR", error=e))
                continue

            detections = tracker.update_with_detections(detections)
            self.motion_count += 1

            # ── Confidence voting ─────────────────────────────────────────
            for tid, cid, conf in zip(
                detections.tracker_id,
                detections.class_id,
                detections.confidence,
            ):
                if tid is None:
                    continue
                cls_name = CLASS_NAMES.get(int(cid), str(cid))
                if cls_name in CLASS_WEIGHTS:
                    track_class_votes[tid][cls_name] += float(conf)

            # ── RL frame capture ──────────────────────────────────────────
            if RL_ENABLED:
                for xyxy, tid, cid, conf in zip(
                    detections.xyxy, detections.tracker_id,
                    detections.class_id, detections.confidence,
                ):
                    if tid is None:
                        continue
                    cx = int((xyxy[0] + xyxy[2]) / 2)
                    if abs(cx - CROSS_LINE) <= RL_PROX and conf < RL_CONF:
                        label = CLASS_NAMES.get(int(cid), "unknown")
                        _save_rl_frame(color_frame, self.session_id,
                                       self.transaction_id, label, float(conf))

            # ── Build labels for supervision annotator ────────────────────
            labels = []
            for tid, cid, conf in zip(
                detections.tracker_id, detections.class_id, detections.confidence,
            ):
                if tid is None:
                    labels.append("UNK")
                    continue
                best = get_best_class(tid) or CLASS_NAMES.get(int(cid), "UNK")
                labels.append(f"{best} {conf:.2f} ID:{tid}")

            # ── Annotate exactly like old system ──────────────────────────
            annotated = box_annotator.annotate(color_frame.copy(), detections)
            annotated = label_annotator.annotate(annotated, detections, labels)

            # White count line thickness=3
            cv2.line(annotated, (CROSS_LINE, 0), (CROSS_LINE, fh),
                     (255, 255, 255), 3)
            cv2.putText(annotated, "COUNT LINE",
                (CROSS_LINE + 5, 20), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (255, 255, 255), 2)

            # Count bar bottom-left
            count_text = " | ".join(f"{k}:{v}" for k, v in self.counts.items())
            cv2.putText(annotated, count_text,
                (10, fh - 20), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (255, 255, 255), 2)

            # ── Line crossing + counting ──────────────────────────────────
            for xyxy, tid in zip(detections.xyxy, detections.tracker_id):
                if tid is None:
                    continue
                cx = int((xyxy[0] + xyxy[2]) / 2)
                if tid in prev_x:
                    old_cx = prev_x[tid]
                    crossed = (old_cx > CROSS_LINE >= cx
                               if CROSS_DIR == "left"
                               else old_cx < CROSS_LINE <= cx)
                    if crossed and tid not in counted_ids:
                        best_cls = get_best_class(tid)
                        if best_cls is None:
                            prev_x[tid] = cx
                            continue
                        if best_cls in CLASS_WEIGHTS:
                            counted_ids.add(tid)
                            weight = BAG_CLASSES.get(best_cls, 1)
                            counter = "bag"
                            self.counts[counter] += weight

                            # Trolley — 3 sec window
                            now = time.time()
                            if now - self._last_trolley > self._trolley_win:
                                self.counts["trolley"] += 1
                                self._last_trolley = now

                            logger.info(LOG("TRACK.003.INFO",
                                cls=best_cls, old_cx=old_cx,
                                cx=cx, total=self.counts[counter]))

                            # Save annotated trip image
                            self.frame_saver.save_detected_frame(
                                annotated, tracked=detections,
                                counts=self.counts.copy())

                            # Update DB
                            self._update_db()
                            if self.on_count:
                                try:
                                    self.on_count(self.session_id,
                                                  self.counts.copy())
                                except Exception:
                                    pass
                prev_x[tid] = cx

            # ── Write to detected video ───────────────────────────────────
            self.video_writer.write(annotated)

        cap.release()

    def _update_db(self):
        c = self.counts
        update_counts(
            transaction_id=self.transaction_id,
            box_count=c.get("box", 0),
            bale_count=c.get("bale", 0),
            bag_count=c.get("bag", 0),
            trolley_count=c.get("trolley", 0),
            image_path=self.frame_saver.get_image_paths_json(),
        )
        upsert(
            session_id=self.session_id,
            transaction_id=self.transaction_id,
            cam=self.cam,
            box_count=c.get("box", 0),
            bale_count=c.get("bale", 0),
            trolley_count=c.get("trolley", 0),
            bag_count=c.get("bag", 0),
        )
        publish_counts(self.session_id, self.transaction_id, self.counts)
