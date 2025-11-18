# main.py — YOLOv5 Detection Backend (smart logging + MQTT error push)
# ===================================================================

# Import the smart logger first (reads logging.properties)
from smart_logger import get_logger
logger = get_logger(__name__)

# Keep import of logging for compatibility in rare libs that expect it
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import cv2
import torch
import numpy as np
import sys
import os
from datetime import datetime
import time
import shutil
import psutil  # for memory usage

from session import session_manager

# MQTT error publisher + connect
from mqtt_push import mqtt_push_error, mqtt_connect

# Messages loader (from messages.properties)
from message_loader import Messages

# ---- Import Config from config_loader ----
from config_loader import (
    YOLOV5_PATH,
    MODEL_PATH,
    FRAME_WIDTH,
    FRAME_HEIGHT,
    CROSS_LINE_X,
    CONF_THRES,
    RTMP_BASE_URL,
    VIDEO_SAVE_DIR,
    DAYS_TO_KEEP,
    FASTAPI_TITLE,
    ALLOWED_ORIGINS,
    HOST,
    PORT,
)


# ------------------ Helper ------------------
def gui_available():
    """Check if OpenCV GUI is available."""
    available = not (sys.platform.startswith("linux") and not os.environ.get("DISPLAY"))
    logger.debug(
        "gui_available -> %s (platform=%s, DISPLAY=%s)",
        available, sys.platform, os.environ.get("DISPLAY")
    )
    return available


def get_tx_for_session(session_id: str):
    """
    Helper: safely get transaction_id for a session.
    Returns None if not available.
    """
    try:
        sess = session_manager.sessions.get(session_id)
        if not sess:
            return None
        return sess.get("transaction_id")
    except Exception:
        logger.exception(
            Messages.get("SESSION.TXID.001.ERROR", session_id=session_id)
        )
        return None

# ------------------ NEW: Single-session lock ------------------
def any_active_session_exists() -> bool:
    """
    Returns True if ANY detection session is currently active.
    Prevents multiple detection sessions from running at once.
    """
    try:
        for sid in session_manager.sessions.keys():
            try:
                if session_manager.is_active(sid):
                    logger.warning(
                        Messages.get("CAMERA.SESSION.001.WARN", session_id=sid)
                    )
                    return True
            except Exception:
                return True   # fail-safe
        return False
    except Exception:
        return True  # fail-safe


# ------------------ FastAPI App ------------------
app = FastAPI(title=FASTAPI_TITLE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------ Request Models ------------------
class DetectionRequest(BaseModel):
    name: str
    role: str
    user_id: str
    device_unique_id: str
    vehicle_number: str
    video_url: str
    session_id: str
    transaction_id: str


class StopRequest(BaseModel):
    session_id: str
    transaction_id: str

class StatusRequest(BaseModel):
    session_id: str


# ------------------ Startup Cleanup + MQTT ------------------
@app.on_event("startup")
async def startup_event():
    logger.info(Messages.get("API.STARTUP.001.INFO"))

    # 1) Connect to MQTT broker
    try:
        mqtt_connect()
        logger.info(Messages.get("API.STARTUP.002.INFO"))
    except Exception:
        logger.exception(Messages.get("API.STARTUP.003.ERROR"))


# ------------------ Load YOLOv5 Model ------------------
try:
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    logger.debug("Torch available: cuda=%s", torch.cuda.is_available())

    # load custom model from local yolov5 repo
    logger.info(
        Messages.get(
            "YOLO.LOAD.001.INFO",
            yolo_path=YOLOV5_PATH,
            model_path=MODEL_PATH,
        )
    )
    model = torch.hub.load(
        YOLOV5_PATH, "custom",
        path=MODEL_PATH,
        source="local"
    )

    # configure model thresholds
    model.conf = CONF_THRES
    logger.debug("Set model.conf = %s", CONF_THRES)

    if device.startswith("cuda"):
        model.to(device)
        logger.info("✅ Model moved to device: %s", device)
    else:
        logger.info("✅ Model running on CPU")

    logger.info(
        Messages.get("YOLO.LOAD.002.INFO", device=device)
    )

except Exception:
    logger.exception(Messages.get("YOLO.LOAD.003.ERROR"))
    raise RuntimeError("YOLOv5 model loading failed")


# ------------------ Detection Core ------------------
async def detect_objects(video_source, session_id):
    logger.info(
        Messages.get(
            "DETECTION.START.001.INFO",
            session_id=session_id,
            video_source=video_source,
        )
    )
    start_ts = datetime.now()
    loop_start_time = time.time()

    try:
        # Open capture
        cap = cv2.VideoCapture(video_source, cv2.CAP_FFMPEG)
        logger.debug(
            "Opened VideoCapture for source=%s (isOpened=%s)",
            video_source, cap.isOpened()
        )

        transaction_id = get_tx_for_session(session_id)

        if not cap.isOpened():
            logger.error(Messages.get("CAMERA.OPEN.001.ERROR"))

            # Send camera-disconnected error to frontend
            try:
                mqtt_push_error(
                    session_id=session_id,
                    transaction_id=transaction_id,
                    error_code="CAMERA_DISCONNECTED",
                    message="Camera source could not be opened",
                    severity="critical",
                )
            except Exception:
                logger.exception("Failed to push CAMERA_DISCONNECTED MQTT error")

            # ensure session is stopped and DB/state cleaned up
            try:
                session_manager.stop_session(session_id)
            except Exception:
                logger.exception("Error while stopping session after failed capture open")
            return

        tracker = session_manager.get_tracker(session_id)
        counts = session_manager.get_counts(session_id)
        prev_centers_x = {}

        # For FPS and periodic checks
        frame_index = 0
        last_disk_check_time = time.time()
        fps_warning_sent = False

        # Optional OpenCV Window
        if gui_available():
            try:
                window_name = f"Detection-{session_id}"
                cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(window_name, FRAME_WIDTH, FRAME_HEIGHT)
                logger.debug(
                    Messages.get("CAMERA.GUI.001.DEBUG", session_id=session_id)
                )
            except Exception:
                logger.exception(
                    Messages.get("CAMERA.GUI.002.ERROR", session_id=session_id)
                )

        while session_manager.is_active(session_id):
            frame_index += 1
            ret, frame = cap.read()
            logger.debug(
                "Read frame #%d (ret=%s) for session=%s",
                frame_index, ret, session_id
            )

            if not ret:
                logger.warning(
                    Messages.get(
                        "CAMERA.FRAME.001.WARN",
                        session_id=session_id,
                        frame_index=frame_index,
                    )
                )
                try:
                    mqtt_push_error(
                        session_id=session_id,
                        transaction_id=transaction_id,
                        error_code="NO_FRAMES",
                        message="No frames received from camera source",
                        severity="high",
                    )
                except Exception:
                    logger.exception("Failed to push NO_FRAMES MQTT error")
                break

            # ------------------ MEMORY CHECK (periodic) ------------------
            try:
                if frame_index % 60 == 0:  # every ~60 frames
                    mem_percent = psutil.virtual_memory().percent
                    if mem_percent > 90:
                        logger.warning(
                            Messages.get(
                                "SYSTEM.MEMORY.001.WARN",
                                percent=mem_percent,
                            )
                        )
                        mqtt_push_error(
                            session_id=session_id,
                            transaction_id=transaction_id,
                            error_code="MEMORY_HIGH",
                            message=f"Memory usage {mem_percent}%",
                            severity="critical",
                        )
            except Exception:
                logger.exception(Messages.get("SYSTEM.MEMORY.002.ERROR"))

            # ------------------ DISK SPACE CHECK (periodic) --------------
            try:
                now = time.time()
                if now - last_disk_check_time > 30:  # every 30 seconds
                    last_disk_check_time = now
                    try:
                        total, used, free = shutil.disk_usage(VIDEO_SAVE_DIR)
                    except Exception:
                        # fallback to root if VIDEO_SAVE_DIR causes issue
                        total, used, free = shutil.disk_usage("/")

                    free_mb = free // (1024 * 1024)
                    if free < 1_000_000_000:  # < 1 GB
                        logger.warning(
                            Messages.get(
                                "SYSTEM.DISK.001.WARN",
                                free_mb=free_mb,
                            )
                        )
                        mqtt_push_error(
                            session_id=session_id,
                            transaction_id=transaction_id,
                            error_code="DISK_SPACE_LOW",
                            message=f"Only {free_mb} MB free on server",
                            severity="critical",
                        )
            except Exception:
                logger.exception(Messages.get("SYSTEM.DISK.002.ERROR"))

            # ------------------ FPS CHECK (periodic) ---------------------
            try:
                now = time.time()
                elapsed = now - loop_start_time
                if elapsed > 0 and frame_index % 60 == 0:  # approximate check
                    fps = frame_index / elapsed
                    logger.debug(
                        "Current approx FPS for session %s: %.2f",
                        session_id, fps
                    )
                    if fps < 5 and not fps_warning_sent:
                        fps_warning_sent = True
                        mqtt_push_error(
                            session_id=session_id,
                            transaction_id=transaction_id,
                            error_code="FPS_DROP",
                            message=f"Detection FPS dropped to {fps:.2f}",
                            severity="medium",
                        )
            except Exception:
                logger.exception(Messages.get("SYSTEM.FPS.002.ERROR"))

            # -------------------------------------------------------------
            try:
                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
            except Exception:
                logger.exception("Failed to resize frame; continuing with original size")

            # Save the first frame
            if not session_manager.sessions[session_id]["first_frame_saved"]:
                try:
                    session_manager.video_saver.save_first_frame(session_id, frame)
                    session_manager.sessions[session_id]["first_frame_saved"] = True
                    logger.debug(
                        Messages.get(
                            "DETECTION.FIRST_FRAME.001.DEBUG",
                            session_id=session_id,
                        )
                    )
                except Exception:
                    logger.exception(
                        Messages.get(
                            "DETECTION.FIRST_FRAME.002.ERROR",
                            session_id=session_id,
                        )
                    )

            # Run YOLO (convert to RGB as expected)
            try:
                img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            except Exception:
                logger.exception(
                    "Failed to convert frame BGR->RGB; using original frame for inference"
                )
                img_rgb = frame

            try:
                results = model(img_rgb)
                # results.xyxy[0] contains columns [x1, y1, x2, y2, conf, cls]
                dets = results.xyxy[0].cpu().numpy() if hasattr(results, "xyxy") else np.array([])
                logger.debug(
                    Messages.get(
                        "DETECTION.YOLO.001.DEBUG",
                        count=len(dets),
                        frame_index=frame_index,
                    )
                )
            except Exception as e:
                logger.exception(
                    Messages.get(
                        "DETECTION.YOLO.002.ERROR",
                        frame_index=frame_index,
                        error=e,
                    )
                )
                dets = np.array([])
                try:
                    mqtt_push_error(
                        session_id=session_id,
                        transaction_id=transaction_id,
                        error_code="YOLO_INFERENCE_ERROR",
                        message=f"YOLO failed on frame {frame_index}: {e}",
                        severity="high",
                    )
                except Exception:
                    logger.exception("Failed to push YOLO_INFERENCE_ERROR MQTT message")

            centers, labels_this_frame = [], {}

            for det in dets:
                try:
                    x1, y1, x2, y2, conf, cls = det
                    if conf < CONF_THRES:
                        logger.debug(
                            "Skipping detection with conf=%s below threshold=%s",
                            conf, CONF_THRES
                        )
                        continue

                    cls = int(cls)
                    label_name = model.names.get(cls, str(cls))
                    cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
                    centers.append((cx, cy))
                    labels_this_frame[(cx, cy)] = label_name

                    # draw boxes on frame for saver/display
                    cv2.rectangle(
                        frame,
                        (int(x1), int(y1)), (int(x2), int(y2)),
                        (0, 255, 0), 2
                    )
                    cv2.putText(
                        frame, f"{label_name} {conf:.2f}",
                        (int(x1), int(y1) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1
                    )

                    logger.debug(
                        "Detection -> label=%s conf=%.3f bbox=(%d,%d,%d,%d) center=(%d,%d)",
                        label_name, float(conf),
                        int(x1), int(y1), int(x2), int(y2),
                        cx, cy
                    )
                except Exception:
                    logger.exception(
                        "Error while processing single detection on frame #%d",
                        frame_index
                    )

            # Update tracker with centers
            try:
                assigned = tracker.update(centers)
                logger.debug(
                    Messages.get(
                        "DETECTION.TRACKER.001.DEBUG",
                        assigned_count=len(assigned),
                        session_id=session_id,
                    )
                )
            except Exception:
                logger.exception(
                    Messages.get(
                        "DETECTION.TRACKER.002.ERROR",
                        session_id=session_id,
                    )
                )
                assigned = {}

            frame_has_crossing = False
            crossing_label = None

            for obj_id, (cx, cy) in assigned.items():
                try:
                    # find label for this tracked center (allow small tolerance)
                    label_name = next(
                        (lbl for (lx, ly), lbl in labels_this_frame.items()
                         if abs(lx - cx) < 6 and abs(ly - cy) < 6),
                        None
                    )

                    if not label_name:
                        logger.debug(
                            "No label found for object_id=%s center=(%s,%s)",
                            obj_id, cx, cy
                        )
                        continue

                    prev_x = prev_centers_x.get(obj_id)

                    # crossing detection: leftward cross of CROSS_LINE_X
                    if prev_x and prev_x > CROSS_LINE_X and cx <= CROSS_LINE_X:
                        counts = session_manager.update_counts(session_id, label_name)
                        frame_has_crossing = True
                        crossing_label = label_name
                        logger.info(
                            Messages.get(
                                "DETECTION.CROSSING.001.INFO",
                                session_id=session_id,
                                object_id=obj_id,
                                label=label_name,
                                counts=counts,
                            )
                        )
                    prev_centers_x[obj_id] = cx
                except Exception:
                    logger.exception(
                        Messages.get(
                            "DETECTION.TRACKER.003.ERROR",
                            object_id=obj_id,
                            session_id=session_id,
                        )
                    )

            # Draw crossing line and display counts on frame
            try:
                cv2.line(
                    frame,
                    (CROSS_LINE_X, 0),
                    (CROSS_LINE_X, FRAME_HEIGHT),
                    (0, 255, 255), 2
                )
                text = (
                    f"Box: {counts['box']} | "
                    f"Bale: {counts['bale']} | "
                    f"Trolley: {counts['trolley']}"
                )
                cv2.putText(
                    frame, text,
                    (10, FRAME_HEIGHT - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (255, 255, 255), 2
                )
            except Exception:
                logger.exception(
                    Messages.get(
                        "DETECTION.COUNTLINE.001.ERROR",
                        session_id=session_id,
                    )
                )

            # Save counted frame if crossing occurred
            if frame_has_crossing and crossing_label is not None:
                try:
                    session_manager.frame_saver.save_counted_frame(
                        session_id, frame, crossing_label
                    )
                    logger.debug(
                        "Saved counted frame for session=%s (label=%s)",
                        session_id, crossing_label
                    )
                except Exception:
                    logger.exception(
                        Messages.get(
                            "DETECTION.FRAMESAVER.001.ERROR",
                            session_id=session_id,
                        )
                    )

            # Always write frame to video saver (non-blocking)
            try:
                session_manager.video_saver.write_frame(session_id, frame)
            except Exception:
                logger.exception(
                    Messages.get(
                        "DETECTION.VIDEOSAVER.001.ERROR",
                        session_id=session_id,
                    )
                )

            # Show GUI if available
            if gui_available():
                try:
                    win = f"Detection-{session_id}"
                    cv2.imshow(win, frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        logger.info(
                            Messages.get(
                                "CAMERA.GUI.003.INFO",
                                session_id=session_id,
                            )
                        )
                        session_manager.stop_session(session_id)
                        break
                except Exception:
                    logger.exception(
                        Messages.get(
                            "CAMERA.GUI.004.ERROR",
                            session_id=session_id,
                        )
                    )

            # update counts in session state
            try:
                session_manager.set_counts(session_id, counts)
            except Exception:
                logger.exception(
                    "Failed to set counts in session_manager for session=%s",
                    session_id
                )

            # cooperative multitasking yield
            await asyncio.sleep(0)

        # cleanup capture + windows
        try:
            cap.release()
            logger.debug("Released VideoCapture for session=%s", session_id)
        except Exception:
            logger.exception("Failed to release VideoCapture for session=%s", session_id)

        if gui_available():
            try:
                cv2.destroyAllWindows()
            except Exception:
                logger.exception(
                    "Failed to destroy OpenCV windows post-session %s",
                    session_id
                )

        logger.info(
            Messages.get(
                "DETECTION.STOP.001.INFO",
                session_id=session_id,
                duration=(datetime.now() - start_ts),
            )
        )

    except Exception:
        logger.exception(
            Messages.get(
                "DETECTION.EXCEPTION.001.ERROR",
                session_id=session_id,
            )
        )
        try:
            # Generic detection error propagated to UI
            transaction_id = get_tx_for_session(session_id)
            mqtt_push_error(
                session_id=session_id,
                transaction_id=transaction_id,
                error_code="DETECTION_EXCEPTION",
                message="Unexpected detection error in backend",
                severity="high",
            )
        except Exception:
            logger.exception("Failed to push DETECTION_EXCEPTION MQTT error")

        try:
            session_manager.stop_session(session_id)
        except Exception:
            logger.exception(
                "Error while stopping session after detection exception (%s)",
                session_id
            )


@app.post("/status")
async def post_status(data: StatusRequest):
    try:
        session_id = data.session_id

        active = session_manager.is_active(session_id)

        return {
            "session_id": session_id,
            "active": active
        }

    except Exception:
        logger.exception(Messages.get("API.STATUS.001.ERROR"))
        raise HTTPException(status_code=500, detail="Status check failed")




# ------------------ API: START ------------------
@app.post("/start")
async def start_detection(data: DetectionRequest):
    logger.debug("Received /start request payload: %s", data.dict())
    try:
        logger.info(
            Messages.get(
                "SESSION.START.001.INFO",
                session_id=data.session_id,
            )
        )

        if not data.transaction_id:
            logger.warning(
                Messages.get(
                    "SESSION.START.002.WARN",
                    session_id=data.session_id,
                )
            )
            raise HTTPException(status_code=400, detail="Transaction ID is required")

        if not session_manager.db.user_exists(data.user_id, data.device_unique_id):
            logger.warning(
                Messages.get(
                    "SESSION.START.003.WARN",
                    user_id=data.user_id,
                    device_id=data.device_unique_id,
                )
            )
            raise HTTPException(status_code=404, detail="User not found")
        
        # 🔒 Block if ANY other session is running
        if any_active_session_exists():
            logger.error(
                 Messages.get(
                "SESSION.START.005.ERROR",
             session_id=data.session_id
            )
         )
            raise HTTPException(
                status_code=400,
                detail="Another detection session is already running. Stop it first.",
            )

        if session_manager.session_exists(data.session_id):
            logger.warning(
                Messages.get(
                    "SESSION.START.004.WARN",
                    session_id=data.session_id,
                )
            )
            raise HTTPException(status_code=400, detail="Session already running")

        stream_url = f"{RTMP_BASE_URL}{data.video_url}"
        logger.debug(
            "Resolved stream_url=%s for provided video_url=%s",
            stream_url, data.video_url
        )

        session_manager.start_session(
            session_id=data.session_id,
            name=data.name,
            role=data.role,
            user_id=data.user_id,
            device_unique_id=data.device_unique_id,
            vehicle_number=data.vehicle_number,
            video_url=stream_url,
            transaction_id=data.transaction_id,
        )

        # create detection task
        asyncio.create_task(detect_objects(stream_url, data.session_id))
        logger.info(
            Messages.get(
                "SESSION.START.007.INFO",
                session_id=data.session_id,
            )
        )

        return {
            "message": "Detection started",
            "session_id": data.session_id,
            "transaction_id": data.transaction_id,
        }

    except HTTPException:
        # re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.exception(
            Messages.get(
                "SESSION.START.006.ERROR",
                session_id=getattr(data, "session_id", None),
            )
        )
        # push generic start error to UI
        try:
            mqtt_push_error(
                session_id=data.session_id,
                transaction_id=data.transaction_id,
                error_code="START_DETECTION_ERROR",
                message=str(e),
                severity="high",
            )
        except Exception:
            logger.exception("Failed to push START_DETECTION_ERROR MQTT error")

        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------ API: STOP ------------------
@app.post("/stop")
async def stop_detection(data: StopRequest):
    logger.debug("Received /stop payload: %s", data.dict())
    try:
        if not data.transaction_id:
            logger.warning(Messages.get("SESSION.STOP.006.ERROR"))
            raise HTTPException(status_code=400, detail="Transaction ID required")

        if not session_manager.session_exists(data.session_id):
            logger.warning(
                Messages.get(
                    "SESSION.STOP.007.ERROR",
                    session_id=data.session_id,
                )
            )
            raise HTTPException(status_code=404, detail="Session not found")

        session_manager.stop_session(data.session_id)
        logger.info("🛑 Stop request processed for session=%s", data.session_id)

        return {
            "message": "Detection stopped",
            "transaction_id": data.transaction_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(Messages.get("SESSION.STOP.008.ERROR"))
        try:
            mqtt_push_error(
                session_id=data.session_id,
                transaction_id=data.transaction_id,
                error_code="STOP_DETECTION_ERROR",
                message=str(e),
                severity="medium",
            )
        except Exception:
            logger.exception("Failed to push STOP_DETECTION_ERROR MQTT error")

        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------ API: GET COUNT ------------------
@app.get("/count/{session_id}")
async def get_detection_count(session_id: str):
    logger.debug("Received /count request for session=%s", session_id)
    if not session_manager.session_exists(session_id):
        logger.warning(
            Messages.get(
                "API.COUNT.001.WARN",
                session_id=session_id,
            )
        )
        raise HTTPException(status_code=404, detail="Session not found")

    counts = session_manager.get_counts(session_id)
    logger.debug("Returning counts for session=%s -> %s", session_id, counts)
    return {
        "session_id": session_id,
        "counts": counts,
    }


# ------------------ Entry Point ------------------
if __name__ == "__main__":
    import uvicorn
    logger.info(
        Messages.get(
            "SERVER.UVICORN.001.INFO",
            host=HOST,
            port=PORT,
        )
    )
    uvicorn.run(app, host=HOST, port=PORT)
