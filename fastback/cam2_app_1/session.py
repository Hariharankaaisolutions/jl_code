# session.py — Full Session Management with SmartLogger + Message Loader
# ========================================================================

from smart_logger import get_logger
logger = get_logger(__name__)

from message_loader import Messages   # ✅ Added

import gc
from datetime import datetime
import numpy as np

from mail import send_email
from video_saver import VideoSaver
from detected_frame_saver import DetectedFrameSaver
from database import DetectionDatabase
from database_updater import DatabaseUpdater
from mqtt_push import mqtt_push_counts_cam2  # NOTE: mqtt_connect REMOVED

from config_loader import (
    BAG_CLASSES,
    TRACKER_MAX_DISTANCE,
    DEFAULT_COUNTS,
    VIDEO_FRAME_WIDTH,
    VIDEO_FRAME_HEIGHT,
    VIDEO_FPS,
    DB_NAME,
    MQTT_ENABLED,
    ENABLE_GC_CLEANUP,
)


# ============================================================================ #
# Centroid Tracker (Fully Logged)
# ============================================================================ #
class CentroidTracker:
    def __init__(self, max_distance=TRACKER_MAX_DISTANCE):
        logger.debug(
            Messages.get("TRACKER.INIT.001.DEBUG", max_distance=max_distance)
        )
        self.next_id = 0
        self.objects = {}
        self.max_distance = max_distance
        self.seen_ids = set()

    def update(self, centers):
        logger.debug(
            Messages.get("TRACKER.UPDATE.001.DEBUG", centers=centers)
        )

        new_objects = {}

        # First frame
        if len(self.objects) == 0:
            logger.debug(Messages.get("TRACKER.UPDATE.002.DEBUG"))
            for c in centers:
                obj_id = self.next_id
                self.next_id += 1
                self.objects[obj_id] = c
                new_objects[obj_id] = c
                self.seen_ids.add(obj_id)

                logger.debug(
                    Messages.get("TRACKER.NEWOBJ.001.DEBUG", obj_id=obj_id, center=c)
                )
            return new_objects

        unmatched_centers = centers.copy()
        existing_ids = list(self.objects.keys())
        existing_centers = list(self.objects.values())

        logger.debug(
            Messages.get("TRACKER.UPDATE.003.DEBUG", existing=self.objects)
        )

        if existing_centers and unmatched_centers:
            # distance matrix
            dist_matrix = np.zeros((len(existing_centers), len(unmatched_centers)), float)

            for i, ec in enumerate(existing_centers):
                for j, nc in enumerate(unmatched_centers):
                    dist_matrix[i, j] = np.hypot(ec[0] - nc[0], ec[1] - nc[1])

            logger.debug(
                Messages.get("TRACKER.UPDATE.004.DEBUG", matrix=dist_matrix)
            )

            matched_existing = set()
            matched_centers = set()

            while True:
                idx = np.unravel_index(np.argmin(dist_matrix), dist_matrix.shape)
                min_val = dist_matrix[idx]

                if min_val > self.max_distance:
                    logger.debug(
                        Messages.get(
                            "TRACKER.MATCH.005.DEBUG",
                            min_val=min_val,
                            max_distance=self.max_distance
                        )
                    )
                    break

                i, j = idx
                if i in matched_existing or j in matched_centers:
                    dist_matrix[i, j] = np.inf
                    if np.isinf(dist_matrix).all():
                        break
                    continue

                obj_id = existing_ids[i]
                center = tuple(map(int, unmatched_centers[j]))

                self.objects[obj_id] = center
                new_objects[obj_id] = center

                logger.debug(
                    Messages.get(
                        "TRACKER.MATCH.001.DEBUG",
                        obj_id=obj_id,
                        center=center,
                        distance=min_val
                    )
                )

                matched_existing.add(i)
                matched_centers.add(j)

                dist_matrix[i, :] = np.inf
                dist_matrix[:, j] = np.inf

            # Remaining new objects
            for j, nc in enumerate(unmatched_centers):
                if j not in matched_centers:
                    obj_id = self.next_id
                    self.next_id += 1
                    center = tuple(map(int, nc))

                    self.objects[obj_id] = center
                    new_objects[obj_id] = center
                    self.seen_ids.add(obj_id)

                    logger.debug(
                        Messages.get(
                            "TRACKER.NEWOBJ.002.DEBUG",
                            obj_id=obj_id,
                            center=center
                        )
                    )

        else:
            logger.debug("No existing objects — registering all new objects")
            for c in unmatched_centers:
                obj_id = self.next_id
                self.next_id += 1
                center = tuple(map(int, c))
                self.objects[obj_id] = center
                new_objects[obj_id] = center
                self.seen_ids.add(obj_id)

                logger.debug(
                    Messages.get(
                        "TRACKER.NEWOBJ.003.DEBUG",
                        obj_id=obj_id,
                        center=center
                    )
                )

        logger.debug("Tracker update done new_objects=%s", new_objects)
        return new_objects

    def total_seen(self):
        logger.debug(
            Messages.get("TRACKER.TOTALSEEN.001.DEBUG", total=len(self.seen_ids))
        )
        return len(self.seen_ids)


# ============================================================================ #
# Session Manager (Fully Logged)
# ============================================================================ #
class SessionManager:
    def __init__(self):
        logger.info(
            Messages.get("SESSION.INIT.001.INFO", mqtt_enabled=MQTT_ENABLED)
        )

        self.sessions = {}
        self.previous_counts = {}

        self.video_saver = VideoSaver()
        self.frame_saver = DetectedFrameSaver(on_frame_saved=self._on_frame_saved)

        self.db = DetectionDatabase(dbname=DB_NAME)
        self.db_updater = DatabaseUpdater()

        logger.info(Messages.get("SESSION.INIT.002.INFO"))
    # ----------------------------------------------------------------------
    # Frame Save Callback
    # ----------------------------------------------------------------------
    def _on_frame_saved(self, session_id, image_path):
        logger.debug(
            Messages.get(
                "FRAME.SAVER.009.DEBUG",
                session_id=session_id,
                frame_path=image_path
            )
        )
        if session_id in self.sessions:
            self.sessions[session_id]["image_path"] = image_path
            logger.info(
                Messages.get(
                    "FRAME.SAVER.008.INFO",
                    session_id=session_id,
                    filename=image_path,
                    label=""  # label not available here
                )
            )

    # ----------------------------------------------------------------------
    # Start Session
    # ----------------------------------------------------------------------
    def start_session(
        self,
        session_id,
        name,
        role,
        user_id,
        device_unique_id,
        vehicle_number,
        video_url,
        transaction_id=None
    ):
        logger.info(
            Messages.get("SESSION.START.012.INFO", session_id=session_id)
        )

        cam = video_url.split('/')[-1]
        start_time = datetime.now().strftime("%H:%M:%S")

        logger.debug(
            Messages.get(
                "SESSION.START.013.DEBUG",
                name=name,
                role=role,
                user_id=user_id,
                device=device_unique_id,
                video_url=video_url,
                cam=cam
            )
        )

        self.sessions[session_id] = {
            "name": name,
            "role": role,
            "user_id": user_id,
            "device_unique_id": device_unique_id,
            "vehicle_number": vehicle_number,
            "video_url": video_url,
            "cam": cam,
            "start_time": start_time,
            "active": True,
            "counts": DEFAULT_COUNTS.copy(),
            "tracker": CentroidTracker(),
            "first_frame_saved": False,
            "transaction_id": transaction_id,
            "image_path": None,
        }

        logger.debug(
            Messages.get("SESSION.START.014.DEBUG", session_data=self.sessions[session_id])
        )

        # Start video recording
        try:
            self.video_saver.start_recording(
                session_id,
                frame_width=VIDEO_FRAME_WIDTH,
                frame_height=VIDEO_FRAME_HEIGHT,
                fps=VIDEO_FPS
            )
            logger.debug(
                Messages.get("SESSION.VIDEO.001.DEBUG", session_id=session_id)
            )
        except Exception:
            logger.exception(
                Messages.get("SESSION.VIDEO.002.ERROR", session_id=session_id)
            )

        # Insert into DB
        try:
            self.db.insert_session(
                session_id=session_id,
                transaction_id=transaction_id,
                name=name,
                role=role,
                user_id=user_id,
                device_unique_id=device_unique_id,
                cam=cam,
                vehicle_number=vehicle_number,
                start_time=start_time,
                image_path=None,
            )
            logger.info(
                Messages.get("SESSION.DB.001.INFO", session_id=session_id)
            )
        except Exception:
            logger.exception(
                Messages.get("SESSION.DB.002.ERROR", session_id=session_id)
            )

        logger.info(
            Messages.get("SESSION.START.015.INFO", session_id=session_id)
        )

    # ----------------------------------------------------------------------
    # Session State
    # ----------------------------------------------------------------------
    def session_exists(self, session_id):
        exists = session_id in self.sessions and self.sessions[session_id]["active"]
        logger.debug(
            Messages.get("SESSION.STATE.001.DEBUG", session_id=session_id, exists=exists)
        )
        return exists

    def is_active(self, session_id):
        active = self.session_exists(session_id)
        logger.debug(
            Messages.get("SESSION.STATE.002.DEBUG", session_id=session_id, active=active)
        )
        return active

    # ----------------------------------------------------------------------
    # Stop Session
    # ----------------------------------------------------------------------
    def stop_session(self, session_id):
        logger.info(
            Messages.get("SESSION.STOP.013.INFO", session_id=session_id)
        )

        if session_id not in self.sessions:
            logger.error(
                Messages.get("SESSION.STOP.014.ERROR", session_id=session_id)
            )
            return

        session = self.sessions[session_id]
        session["active"] = False

        try:
            video_path = self.video_saver.stop_recording(session_id)
            logger.info(
                Messages.get("SESSION.VIDEO.003.INFO", session_id=session_id, video_path=video_path)
            )
        except Exception:
            logger.exception(
                Messages.get("SESSION.VIDEO.004.ERROR", session_id=session_id)
            )

        try:
            self.cleanup_session(session_id)
        except Exception:
            logger.exception(
                Messages.get("SESSION.CLEANUP.011.ERROR", session_id=session_id)
            )

        try:
            counts = self.sessions[session_id]["counts"]

            send_email(
                subject=f"📊 JL-CAM — Session Completed Successfully",
                body=(
                    f"🕒 End Time:{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"📦 Final Counts:\n"
                    f"   • 👜 Bag: {counts['bag']}\n"
                    f"   • 🛒 Trolley: {counts['trolley']}\n\n"
                    f"🔔 This is an automated notification from JL-CAM System."
                )
            )
            logger.info(
                Messages.get("SESSION.EMAIL.001.INFO", session_id=session_id)
            )

        except Exception:
            logger.exception(
                Messages.get("SESSION.EMAIL.002.ERROR", session_id=session_id)
            )


            logger.info(
                Messages.get("SESSION.STOP.015.INFO", session_id=session_id)
            )

    # ----------------------------------------------------------------------
    # Counts Management
    # ----------------------------------------------------------------------
    def get_tracker(self, session_id):
        logger.debug("get_tracker for session_id=%s", session_id)
        return self.sessions[session_id]["tracker"]

    def update_counts(self, session_id, label_name):
        logger.debug(
            Messages.get(
                "SESSION.COUNTS.003.DEBUG",
                session_id=session_id,
                label=label_name
            )
        )

        counts = self.sessions[session_id]["counts"]

        if label_name in BAG_CLASSES:
            counts["bag"] += BAG_CLASSES[label_name]
        counts["trolley"] += 1

        logger.debug(
            Messages.get("SESSION.COUNTS.004.DEBUG", counts=counts)
        )

        self.previous_counts[session_id] = counts.copy()
        transaction_id = self.sessions[session_id]["transaction_id"]

        # DB update
        try:
            self.db_updater.update_counts_on_multiples(
                transaction_id=transaction_id,
                box_count=counts["box"],
                bale_count=counts["bale"],
                bag_count=counts["bag"],
                trolley_count=counts["trolley"],
                image_path=self.sessions[session_id]["image_path"],
            )
            logger.debug(
                Messages.get("SESSION.DB.003.DEBUG", session_id=session_id)
            )
        except Exception:
            logger.exception(
                Messages.get("SESSION.DB.004.ERROR", session_id=session_id)
            )

        # MQTT publish
        if MQTT_ENABLED:
            try:
                mqtt_push_counts_cam2(
                    session_id=session_id,
                    transaction_id=transaction_id,
                    counts=counts
                )
                logger.debug(
                    Messages.get("SESSION.MQTT.001.DEBUG", session_id=session_id)
                )
            except Exception:
                logger.exception(
                    Messages.get("SESSION.MQTT.002.ERROR", session_id=session_id)
                )

        return counts
    def set_counts(self, session_id, counts):
        logger.debug(
            Messages.get("SESSION.COUNTS.005.DEBUG", session_id=session_id, counts=counts)
        )
        self.sessions[session_id]["counts"] = counts

    def get_counts(self, session_id):
        logger.debug(
            Messages.get("SESSION.COUNTS.006.DEBUG", session_id=session_id)
        )
        return self.sessions[session_id].get("counts", DEFAULT_COUNTS.copy())

    # ----------------------------------------------------------------------
    # Cleanup
    # ----------------------------------------------------------------------
    def cleanup_session(self, session_id):
        logger.info(
            Messages.get("SESSION.CLEANUP.010.INFO", session_id=session_id)
        )

        if session_id not in self.sessions:
            logger.warning(
                Messages.get("SESSION.CLEANUP.012.WARN", session_id=session_id)
            )
            return

        session = self.sessions[session_id]
        transaction_id = session["transaction_id"]
        stop_time = datetime.now().strftime("%H:%M:%S")
        counts = session["counts"]
        image_path = session["image_path"]

        logger.debug(
            Messages.get(
                "SESSION.CLEANUP.013.DEBUG",
                session_id=session_id,
                stop_time=stop_time,
                counts=counts,
                image_path=image_path
            )
        )

        try:
            self.db.update_session_end(
                transaction_id,
                stop_time,
                counts["box"],
                counts["bale"],
                counts["bag"],
                counts["trolley"],
                image_path=image_path,
            )
            logger.info(
                Messages.get("SESSION.CLEANUP.014.INFO", session_id=session_id)
            )
        except Exception:
            logger.exception(
                Messages.get("SESSION.CLEANUP.015.ERROR", session_id=session_id)
            )

        # Remove previous counts
        self.previous_counts.pop(session_id, None)

        # Clear frame saver session cache
        try:
            self.frame_saver.cleanup_session(session_id)
            logger.debug(
                Messages.get("SESSION.CLEANUP.016.DEBUG", session_id=session_id)
            )
        except Exception:
            logger.exception(
                Messages.get("SESSION.CLEANUP.017.ERROR", session_id=session_id)
            )

        # Optional garbage collection
        if ENABLE_GC_CLEANUP:
            try:
                freed = gc.collect()
                logger.debug(
                    Messages.get("SESSION.CLEANUP.018.DEBUG", session_id=session_id, freed=freed)
                )
            except Exception:
                logger.exception(
                    Messages.get("SESSION.CLEANUP.019.ERROR", session_id=session_id)
                )

        logger.info(
            Messages.get("SESSION.CLEANUP.020.INFO", session_id=session_id)
        )


# ============================================================================ #
# Global Instance
# ============================================================================ #
session_manager = SessionManager()
logger.info(Messages.get("SESSION.GLOBAL.001.INFO"))
# End of file — session.py fully integrated with messages.properties
# All compatible log statements replaced using Messages.get()
# All unmatched log lines retained safely
