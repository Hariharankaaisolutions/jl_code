"""
cam1/detection/yolox.py — YOLOX Model
=======================================
Loads and runs YOLOX inference for cam1.
Singleton pattern — model loaded once, reused.
Max 80 lines. One responsibility: YOLOX inference.
"""

import sys
import threading
from pathlib import Path
from typing import Optional

import torch
import numpy as np

from core.config import get, getfloat
from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("YOLOX")

BASE       = Path("/opt/secure_ai")
MODEL_PATH = BASE / get("CAM1_MODEL",    "cam1/models/jl_yolox_cam1.pth")
EXP_FILE   = BASE / get("CAM1_EXP_FILE", "cam1/YOLOX/exps/default/yolox_s.py")
NUM_CLASS  = int(get("CAM1_NUM_CLASSES", "7"))
CONF_THRES = getfloat("CAM1_CONF_THRES", 0.4)
IOU_THRES  = getfloat("CAM1_IOU_THRES",  0.45)
TEST_SIZE  = (640, 640)

CLASS_NAMES = {
    0: "box-Sedr", 1: "bale",    2: "box",
    3: "fbale",    4: "sbale",   5: "tbale_a", 6: "tbale_b",
}

# ── Singleton ──────────────────────────────────────────────────
_model     = None
_exp       = None
_device    = None
_lock      = threading.Lock()


def _load() -> tuple:
    global _model, _exp, _device
    if _model is not None:
        return _model, _exp, _device

    with _lock:
        if _model is not None:
            return _model, _exp, _device
        try:
            yolox_path = str(BASE / "cam1" / "YOLOX")
            if yolox_path not in sys.path:
                sys.path.insert(0, yolox_path)

            import importlib.util
            spec = importlib.util.spec_from_file_location("yolox_exp", str(EXP_FILE))
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            exp            = mod.Exp()
            exp.num_classes = NUM_CLASS
            exp.test_conf   = 0.01
            exp.nmsthre     = IOU_THRES
            exp.test_size   = TEST_SIZE

            device = "cuda:0" if torch.cuda.is_available() else "cpu"
            logger.info(LOG("YOLOX.001.INFO",
                path=str(MODEL_PATH), device=device))

            ckpt  = torch.load(str(MODEL_PATH),
                map_location=device, weights_only=False)
            model = exp.get_model().to(device)
            model.eval()
            model.load_state_dict(ckpt.get("model", ckpt))
            if device == "cuda:0":
                model = model.half()

            _model, _exp, _device = model, exp, device
            logger.info(LOG("YOLOX.002.INFO",
                device=device, classes=NUM_CLASS))
            return _model, _exp, _device

        except Exception as e:
            logger.error(LOG("YOLOX.003.ERROR", error=e))
            raise


def infer(frame: np.ndarray) -> list[dict]:
    """
    Run YOLOX inference on a BGR frame.
    Returns list of dicts: {x1,y1,x2,y2,cx,cy,conf,cls_id,cls_name}
    """
    from yolox.data.data_augment import ValTransform
    from yolox.utils import postprocess

    model, exp, device = _load()

    gray      = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    frame_rgb = cv2.merge([gray, gray, gray])
    preproc   = ValTransform(legacy=False)
    img, _    = preproc(frame_rgb, None, exp.test_size)
    h, w      = frame_rgb.shape[:2]
    ratio     = min(exp.test_size[0]/h, exp.test_size[1]/w)
    tensor    = torch.from_numpy(img).unsqueeze(0).to(device)
    tensor    = tensor.half() if device == "cuda:0" else tensor.float()

    with torch.no_grad():
        out = model(tensor)
        out = postprocess(out, exp.num_classes, exp.test_conf, exp.nmsthre)

    results = []
    if out[0] is not None:
        dets = out[0].cpu().numpy()
        dets[:, 0:4] /= ratio
        for det in dets:
            x1, y1, x2, y2 = det[0:4]
            conf   = float(det[4] * det[5])
            cls_id = int(det[6])
            if conf < CONF_THRES:
                continue
            results.append({
                "x1": int(x1), "y1": int(y1),
                "x2": int(x2), "y2": int(y2),
                "cx": int((x1+x2)/2), "cy": int((y1+y2)/2),
                "conf": conf, "cls_id": cls_id,
                "cls_name": CLASS_NAMES.get(cls_id, "unknown"),
            })
    return results


import cv2  # noqa: E402 — needed after sys.path setup
