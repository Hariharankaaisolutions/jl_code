# session.py — Full Session Management with SmartLogger + Message Loader
# ========================================================================

from smart_logger import get_logger
logger = get_logger(__name__)

from message_loader import Messages

import gc
import json
import time
from datetime import datetime
import numpy as np

from mail import send_email
from video_saver import VideoSaver
from detected_frame_saver import DetectedFrameSaver
from database import DetectionDatabase
from database_updater import DatabaseUpdater
from mqtt_push import mqtt_push_counts

from config_loader import (
    BOX_CLASSES,
    BALE_CLASSES,
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
# Centroid Tracker  (unchanged)
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
        logger.debug(Messages.get("TRACKER.UPDATE.001.DEBUG", centers=centers))

        new_objects = {}

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
        existing_ids      = list(self.objects.keys())
        existing_centers  = list(self.objects.values())

        logger.debug(Messages.get("TRACKER.UPDATE.003.DEBUG", existing=self.objects))

        if existing_centers and unmatched_centers:
            dist_matrix = np.zeros(
                (len(existing_centers), len(unmatched_centers)), float
            )
            for i, ec in enumerate(existing_centers):
                for j, nc in enumerate(unmatched_centers):
                    dist_matrix[i, j] = np.hypot(ec[0] - nc[0], ec[1] - nc[1])

            logger.debug(
                Messages.get("TRACKER.UPDATE.004.DEBUG", matrix=dist_matrix)
            )

            matched_existing = set()
            matched_centers  = set()

            while True:
                idx     = np.unravel_index(np.argmin(dist_matrix), dist_matrix.shape)
                min_val = dist_matrix[idx]

                if min_val > self.max_distance:
                    logger.debug(
                        Messages.get(
                            "TRACKER.MATCH.005.DEBUG",
                            min_val=min_val,
                            max_distance=self.max_distance,
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
                new_objects[obj_id]  = center

                logger.debug(
                    Messages.get(
                        "TRACKER.MATCH.001.DEBUG",
                        obj_id=obj_id,
                        center=center,
                        distance=min_val,
                    )
                )

                matched_existing.add(i)
                matched_centers.add(j)

                dist_matrix[i, :] = np.inf
                dist_matrix[:, j] = np.inf

            for j, nc in enumerate(unmatched_centers):
                if j not in matched_centers:
                    obj_id = self.next_id
                    self.next_id += 1
                    center = tuple(map(int, nc))

                    self.objects[obj_id] = center
                    new_objects[obj_id]  = center
                    self.seen_ids.add(obj_id)

                    logger.debug(
                        Messages.get(
                            "TRACKER.NEWOBJ.002.DEBUG",
                            obj_id=obj_id,
                            center=center,
                        )
                    )

        else:
            logger.debug("No existing objects — registering all new objects")
            for c in unmatched_centers:
                obj_id = self.next_id
                self.next_id += 1
                center = tuple(map(int, c))
                self.objects[obj_id] = center
                new_objects[obj_id]  = center
                self.seen_ids.add(obj_id)

                logger.debug(
                    Messages.get(
                        "TRACKER.NEWOBJ.003.DEBUG",
                        obj_id=obj_id,
                        center=center,
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
# HTML Email Builder — Session Complete
# ============================================================================ #
def _build_session_complete_html(
    name: str,
    role: str,
    vehicle_number: str,
    cam: str,
    date_str: str,
    start_time: str,
    end_time: str,
    counts: dict,
    sent_at: str,
) -> str:
    """
    Build a rich HTML body for the session-complete notification email.
    This is passed as the `body` argument to send_email() which wraps it
    in the standard card layout — but here we return a pre-built HTML string
    directly so send_email() uses it as-is via the html_override parameter.
    """

    # Build counts rows based on camera
    cam_lower = cam.lower()
    if "cam_1" in cam_lower or "cam1" in cam_lower:
        count_rows = f"""
        <tr>
          <td style="padding:10px 16px;color:#78909C;font-size:14px;width:45%;">
            📦 Box
          </td>
          <td style="padding:10px 16px;color:#1A237E;font-size:14px;
                     font-weight:700;">{counts.get('box', 0)}</td>
        </tr>
        <tr style="background:#F8FAFB;">
          <td style="padding:10px 16px;color:#78909C;font-size:14px;">
            🧱 Bale
          </td>
          <td style="padding:10px 16px;color:#1A237E;font-size:14px;
                     font-weight:700;">{counts.get('bale', 0)}</td>
        </tr>
        <tr>
          <td style="padding:10px 16px;color:#78909C;font-size:14px;">
            🛒 Trolley
          </td>
          <td style="padding:10px 16px;color:#4527A0;font-size:14px;
                     font-weight:700;">{counts.get('trolley', 0)}</td>
        </tr>"""
    elif "cam_2" in cam_lower or "cam2" in cam_lower:
        count_rows = f"""
        <tr>
          <td style="padding:10px 16px;color:#78909C;font-size:14px;width:45%;">
            🛍️ Bag
          </td>
          <td style="padding:10px 16px;color:#1A237E;font-size:14px;
                     font-weight:700;">{counts.get('bag', 0)}</td>
        </tr>
        <tr style="background:#F8FAFB;">
          <td style="padding:10px 16px;color:#78909C;font-size:14px;">
            🛒 Trolley
          </td>
          <td style="padding:10px 16px;color:#4527A0;font-size:14px;
                     font-weight:700;">{counts.get('trolley', 0)}</td>
        </tr>"""
    else:
        count_rows = f"""
        <tr>
          <td style="padding:10px 16px;color:#78909C;font-size:14px;width:45%;">
            📦 Box
          </td>
          <td style="padding:10px 16px;color:#1A237E;font-size:14px;
                     font-weight:700;">{counts.get('box', 0)}</td>
        </tr>
        <tr style="background:#F8FAFB;">
          <td style="padding:10px 16px;color:#78909C;font-size:14px;">
            🧱 Bale
          </td>
          <td style="padding:10px 16px;color:#1A237E;font-size:14px;
                     font-weight:700;">{counts.get('bale', 0)}</td>
        </tr>
        <tr>
          <td style="padding:10px 16px;color:#78909C;font-size:14px;">
            🛍️ Bag
          </td>
          <td style="padding:10px 16px;color:#1A237E;font-size:14px;
                     font-weight:700;">{counts.get('bag', 0)}</td>
        </tr>
        <tr style="background:#F8FAFB;">
          <td style="padding:10px 16px;color:#78909C;font-size:14px;">
            🛒 Trolley
          </td>
          <td style="padding:10px 16px;color:#4527A0;font-size:14px;
                     font-weight:700;">{counts.get('trolley', 0)}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Session Complete — JL-CAM</title>
</head>
<body style="margin:0;padding:0;background:#f0f4f8;
             font-family:'Segoe UI',Arial,sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f0f4f8;padding:40px 0;">
    <tr><td align="center">

      <!-- Card -->
      <table width="580" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:16px;
                    box-shadow:0 4px 24px rgba(0,0,0,0.08);overflow:hidden;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#1B5E20,#2E7D32);
                      padding:28px 40px;text-align:center;">
            <div style="font-size:32px;margin-bottom:8px;">✅</div>
            <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;">
              Session Completed
            </h1>
            <p style="margin:8px 0 0;color:#A5D6A7;font-size:13px;">
              JL-CAM Detection System
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px 40px;">

            <!-- Operator Details -->
            <p style="margin:0 0 10px;font-size:11px;font-weight:700;
                       color:#90A4AE;letter-spacing:1px;text-transform:uppercase;">
              Operator Details
            </p>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#F8FAFB;border-radius:12px;
                          border:1px solid #E3EAF0;margin-bottom:24px;">
              <tr>
                <td style="padding:12px 20px;color:#78909C;font-size:14px;width:40%;">
                  👤 Operator
                </td>
                <td style="padding:12px 20px;color:#1A237E;font-size:14px;font-weight:600;">
                  {name} <span style="color:#90A4AE;font-weight:400;">({role})</span>
                </td>
              </tr>
              <tr style="background:#FFFFFF;">
                <td style="padding:12px 20px;color:#78909C;font-size:14px;">
                  🚛 Vehicle No.
                </td>
                <td style="padding:12px 20px;color:#1A237E;font-size:14px;font-weight:600;">
                  {vehicle_number}
                </td>
              </tr>
              <tr>
                <td style="padding:12px 20px;color:#78909C;font-size:14px;">
                  📷 Camera
                </td>
                <td style="padding:12px 20px;color:#1A237E;font-size:14px;font-weight:600;">
                  {cam}
                </td>
              </tr>
            </table>

            <!-- Session Timing -->
            <p style="margin:0 0 10px;font-size:11px;font-weight:700;
                       color:#90A4AE;letter-spacing:1px;text-transform:uppercase;">
              Session Timing
            </p>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#F8FAFB;border-radius:12px;
                          border:1px solid #E3EAF0;margin-bottom:24px;">
              <tr>
                <td style="padding:12px 20px;color:#78909C;font-size:14px;width:40%;">
                  📅 Date
                </td>
                <td style="padding:12px 20px;color:#1A237E;font-size:14px;font-weight:600;">
                  {date_str}
                </td>
              </tr>
              <tr style="background:#FFFFFF;">
                <td style="padding:12px 20px;color:#78909C;font-size:14px;">
                  🕐 Start Time
                </td>
                <td style="padding:12px 20px;color:#1A237E;font-size:14px;font-weight:600;">
                  {start_time}
                </td>
              </tr>
              <tr>
                <td style="padding:12px 20px;color:#78909C;font-size:14px;">
                  🕐 End Time
                </td>
                <td style="padding:12px 20px;color:#1A237E;font-size:14px;font-weight:600;">
                  {end_time}
                </td>
              </tr>
            </table>

            <!-- Final Counts -->
            <p style="margin:0 0 10px;font-size:11px;font-weight:700;
                       color:#90A4AE;letter-spacing:1px;text-transform:uppercase;">
              Final Counts
            </p>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border-radius:12px;border:1px solid #E3EAF0;
                          overflow:hidden;margin-bottom:28px;">
              {count_rows}
            </table>

            <!-- Footer note -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#E8F5E9;border-radius:10px;
                          border-left:4px solid #43A047;">
              <tr>
                <td style="padding:14px 18px;">
                  <p style="margin:0;color:#2E7D32;font-size:13px;line-height:1.5;">
                    ℹ️ Session data has been saved to the database.
                    Video and trip images are available on the server.
                  </p>
                </td>
              </tr>
            </table>

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#F5F7FA;padding:18px 40px;
                      border-top:1px solid #ECEFF1;text-align:center;">
            <p style="margin:0;color:#90A4AE;font-size:12px;line-height:1.6;">
              Sent at {sent_at} &nbsp;|&nbsp;
              Automated notification from <strong>JL-CAM System</strong>.<br>
              Please do not reply to this email.
            </p>
          </td>
        </tr>

      </table>
      <!-- /Card -->

    </td></tr>
  </table>
</body>
</html>"""


# ============================================================================ #
# Session Manager
# ============================================================================ #
class SessionManager:
    def __init__(self):
        logger.info(
            Messages.get("SESSION.INIT.001.INFO", mqtt_enabled=MQTT_ENABLED)
        )

        self.sessions        = {}
        self.previous_counts = {}

        self.video_saver = VideoSaver()
        self.frame_saver = DetectedFrameSaver(on_frame_saved=self._on_frame_saved)

        self.db         = DetectionDatabase(dbname=DB_NAME)
        self.db_updater = DatabaseUpdater()

        logger.info(Messages.get("SESSION.INIT.002.INFO"))

    # ------------------------------------------------------------------
    # Frame Save Callback
    # ------------------------------------------------------------------
    def _on_frame_saved(self, session_id: str, image_path: str):
        if session_id not in self.sessions:
            return

        session = self.sessions[session_id]
        session["image_paths"].append(image_path)

        all_paths_json        = json.dumps(session["image_paths"])
        session["image_path"] = all_paths_json

        logger.debug(
            Messages.get(
                "FRAME.SAVER.009.DEBUG",
                session_id=session_id,
                frame_path=all_paths_json,
            )
        )
        logger.info(
            Messages.get(
                "SESSION.IMAGE.001.DEBUG",
                session_id=session_id,
                total=len(session["image_paths"]),
                paths=all_paths_json,
            )
        )

        transaction_id = session.get("transaction_id")
        counts         = session.get("counts", DEFAULT_COUNTS.copy())

        try:
            self.db_updater.update_counts_on_multiples(
                transaction_id=transaction_id,
                box_count=counts["box"],
                bale_count=counts["bale"],
                bag_count=counts.get("bag", 0),
                trolley_count=counts["trolley"],
                image_path=all_paths_json,
            )
        except Exception:
            logger.exception(
                Messages.get("SESSION.IMAGE.002.ERROR", session_id=session_id)
            )

    # ------------------------------------------------------------------
    # Start Session
    # ------------------------------------------------------------------
    def start_session(
        self,
        session_id,
        name,
        role,
        user_id,
        device_unique_id,
        vehicle_number,
        video_url,
        transaction_id=None,
    ):
        logger.info(Messages.get("SESSION.START.012.INFO", session_id=session_id))

        cam        = video_url.split("/")[-1]
        start_time = datetime.now().strftime("%H:%M:%S")

        logger.debug(
            Messages.get(
                "SESSION.START.013.DEBUG",
                name=name,
                role=role,
                user_id=user_id,
                device=device_unique_id,
                video_url=video_url,
                cam=cam,
            )
        )

        self.sessions[session_id] = {
            "name":              name,
            "role":              role,
            "user_id":           user_id,
            "device_unique_id":  device_unique_id,
            "vehicle_number":    vehicle_number,
            "video_url":         video_url,
            "cam":               cam,
            "start_time":        start_time,
            "active":            True,
            "counts":            DEFAULT_COUNTS.copy(),
            "tracker":           CentroidTracker(),
            "first_frame_saved": False,
            "transaction_id":    transaction_id,
            "image_paths":       [],
            "image_path":        None,
            "last_trolley_time": None,
            "trolley_window":    3,
        }

        logger.debug(
            Messages.get(
                "SESSION.START.014.DEBUG",
                session_data=self.sessions[session_id],
            )
        )

        try:
            self.video_saver.start_recording(
                session_id,
                frame_width=VIDEO_FRAME_WIDTH,
                frame_height=VIDEO_FRAME_HEIGHT,
                fps=VIDEO_FPS,
            )
            logger.debug(Messages.get("SESSION.VIDEO.001.DEBUG", session_id=session_id))
        except Exception:
            logger.exception(Messages.get("SESSION.VIDEO.002.ERROR", session_id=session_id))

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
            logger.info(Messages.get("SESSION.DB.001.INFO", session_id=session_id))
        except Exception:
            logger.exception(Messages.get("SESSION.DB.002.ERROR", session_id=session_id))

        logger.info(Messages.get("SESSION.START.015.INFO", session_id=session_id))

    # ------------------------------------------------------------------
    # Session State
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Stop Session — sends rich HTML session-complete email
    # ------------------------------------------------------------------
    def stop_session(self, session_id):
        logger.info(Messages.get("SESSION.STOP.013.INFO", session_id=session_id))

        if session_id not in self.sessions:
            logger.error(Messages.get("SESSION.STOP.014.ERROR", session_id=session_id))
            return

        session           = self.sessions[session_id]
        session["active"] = False

        # ── Stop video recording ──────────────────────────────────────────
        try:
            video_path = self.video_saver.stop_recording(session_id)
            logger.info(
                Messages.get(
                    "SESSION.VIDEO.003.INFO",
                    session_id=session_id,
                    video_path=video_path,
                )
            )
        except Exception:
            logger.exception(Messages.get("SESSION.VIDEO.004.ERROR", session_id=session_id))

        # ── DB finalise ───────────────────────────────────────────────────
        try:
            self.cleanup_session(session_id)
        except Exception:
            logger.exception(
                Messages.get("SESSION.CLEANUP.011.ERROR", session_id=session_id)
            )

        # ── Session-complete HTML email ───────────────────────────────────
        try:
            counts         = session.get("counts", DEFAULT_COUNTS.copy())
            start_time     = session.get("start_time", "—")
            end_time       = datetime.now().strftime("%H:%M:%S")
            name           = session.get("name",           "Unknown")
            role           = session.get("role",           "—")
            vehicle_number = session.get("vehicle_number", "—")
            cam            = session.get("cam",            "—")
            date_str       = datetime.now().strftime("%Y-%m-%d")
            sent_at        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            subject = (
                f"✅ JL-CAM Session Done"
                f" | {vehicle_number}"
                f" | {name}"
                f" | {date_str}"
                f" | {start_time}–{end_time}"
            )

            html_body = _build_session_complete_html(
                name=name,
                role=role,
                vehicle_number=vehicle_number,
                cam=cam,
                date_str=date_str,
                start_time=start_time,
                end_time=end_time,
                counts=counts,
                sent_at=sent_at,
            )

            # send_email accepts html_override to bypass plain-text conversion
            send_email(subject=subject, body=html_body, is_html=True)

            logger.info(
                Messages.get("SESSION.EMAIL.001.INFO", session_id=session_id)
                if "SESSION.EMAIL.001.INFO" in Messages._messages
                else f"Session-complete email sent for {session_id}"
            )

        except Exception:
            logger.exception(
                Messages.get("SESSION.EMAIL.002.ERROR", session_id=session_id)
                if "SESSION.EMAIL.002.ERROR" in Messages._messages
                else f"Session-complete email FAILED for {session_id}"
            )

        logger.info(Messages.get("SESSION.STOP.015.INFO", session_id=session_id))

    # ------------------------------------------------------------------
    # Tracker
    # ------------------------------------------------------------------
    def get_tracker(self, session_id):
        logger.debug("get_tracker for session_id=%s", session_id)
        return self.sessions[session_id]["tracker"]

    # ------------------------------------------------------------------
    # Counts Management  (unchanged)
    # ------------------------------------------------------------------
    def update_counts(self, session_id: str, label_name: str, frame=None):
        logger.debug(
            Messages.get(
                "SESSION.COUNTS.003.DEBUG",
                session_id=session_id,
                label=label_name,
            )
        )

        session = self.sessions[session_id]
        counts  = session["counts"]

        if label_name in BOX_CLASSES:
            counts["box"] += BOX_CLASSES[label_name]
        elif label_name in BALE_CLASSES:
            counts["bale"] += BALE_CLASSES[label_name]

        now       = time.time()
        last_time = session["last_trolley_time"]
        window    = session["trolley_window"]

        if last_time is None or (now - last_time) > window:
            counts["trolley"] += 1
            session["last_trolley_time"] = now

        logger.debug(Messages.get("SESSION.COUNTS.004.DEBUG", counts=counts))

        if frame is not None:
            try:
                self.frame_saver.save_trip_frame(
                    session_id=session_id,
                    frame=frame,
                    label_name=label_name,
                    trolley_window=window,
                )
            except Exception:
                logger.exception(
                    Messages.get(
                        "DETECTION.FRAMESAVER.001.ERROR",
                        session_id=session_id,
                    )
                )

        self.previous_counts[session_id] = counts.copy()
        transaction_id = session["transaction_id"]

        try:
            self.db_updater.update_counts_on_multiples(
                transaction_id=transaction_id,
                box_count=counts["box"],
                bale_count=counts["bale"],
                bag_count=counts.get("bag", 0),
                trolley_count=counts["trolley"],
                image_path=session["image_path"],
            )
            logger.debug(Messages.get("SESSION.DB.003.DEBUG", session_id=session_id))
        except Exception:
            logger.exception(Messages.get("SESSION.DB.004.ERROR", session_id=session_id))

        if MQTT_ENABLED:
            try:
                mqtt_push_counts(
                    session_id=session_id,
                    transaction_id=transaction_id,
                    counts=counts,
                )
                logger.debug(Messages.get("SESSION.MQTT.001.DEBUG", session_id=session_id))
            except Exception:
                logger.exception(
                    Messages.get("SESSION.MQTT.002.ERROR", session_id=session_id)
                )

        return counts

    def set_counts(self, session_id, counts):
        logger.debug(
            Messages.get(
                "SESSION.COUNTS.005.DEBUG",
                session_id=session_id,
                counts=counts,
            )
        )
        self.sessions[session_id]["counts"] = counts

    def get_counts(self, session_id):
        logger.debug(Messages.get("SESSION.COUNTS.006.DEBUG", session_id=session_id))
        return self.sessions[session_id].get("counts", DEFAULT_COUNTS.copy())

    # ------------------------------------------------------------------
    # Cleanup  (unchanged)
    # ------------------------------------------------------------------
    def cleanup_session(self, session_id):
        logger.info(Messages.get("SESSION.CLEANUP.010.INFO", session_id=session_id))

        if session_id not in self.sessions:
            logger.warning(
                Messages.get("SESSION.CLEANUP.012.WARN", session_id=session_id)
            )
            return

        session        = self.sessions[session_id]
        transaction_id = session["transaction_id"]
        stop_time      = datetime.now().strftime("%H:%M:%S")
        counts         = session["counts"]
        image_paths    = session["image_paths"]

        final_image_path = json.dumps(image_paths) if image_paths else None

        logger.debug(
            Messages.get(
                "SESSION.CLEANUP.013.DEBUG",
                session_id=session_id,
                stop_time=stop_time,
                counts=counts,
                image_path=final_image_path,
            )
        )

        try:
            self.db.update_session_end(
                transaction_id,
                stop_time,
                counts["box"],
                counts["bale"],
                counts.get("bag", 0),
                counts["trolley"],
                image_path=final_image_path,
            )
            logger.info(Messages.get("SESSION.CLEANUP.014.INFO", session_id=session_id))
            logger.info(
                Messages.get(
                    "SESSION.IMAGE.003.INFO",
                    session_id=session_id,
                    total=len(image_paths),
                    paths=final_image_path,
                )
            )
        except Exception:
            logger.exception(
                Messages.get("SESSION.CLEANUP.015.ERROR", session_id=session_id)
            )

        self.previous_counts.pop(session_id, None)

        try:
            self.frame_saver.cleanup_session(session_id)
            logger.debug(Messages.get("SESSION.CLEANUP.016.DEBUG", session_id=session_id))
        except Exception:
            logger.exception(
                Messages.get("SESSION.CLEANUP.017.ERROR", session_id=session_id)
            )

        if ENABLE_GC_CLEANUP:
            try:
                freed = gc.collect()
                logger.debug(
                    Messages.get(
                        "SESSION.CLEANUP.018.DEBUG",
                        session_id=session_id,
                        freed=freed,
                    )
                )
            except Exception:
                logger.exception(
                    Messages.get("SESSION.CLEANUP.019.ERROR", session_id=session_id)
                )

        logger.info(Messages.get("SESSION.CLEANUP.020.INFO", session_id=session_id))


# ============================================================================ #
# Global Instance
# ============================================================================ #
session_manager = SessionManager()
logger.info(Messages.get("SESSION.GLOBAL.001.INFO"))