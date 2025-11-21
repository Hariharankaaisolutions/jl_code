# modules/dash.py

from fastapi import APIRouter
from psycopg2.extras import RealDictCursor
import psycopg2
import os
import json
import paho.mqtt.client as mqtt
import threading
import time
from collections import defaultdict

from utils_config_loader import load_properties
from logger import get_logger

router = APIRouter(tags=["Dash MQTT Dashboard"])
logger = get_logger("dash")

CONFIG = load_properties("config.properties")

DB_HOST = CONFIG.get("DB_HOST", "localhost")
DB_NAME = CONFIG.get("DB_NAME", "jlmill")
DB_USER = CONFIG.get("DB_USER", "kaai")
DB_PASS = CONFIG.get("DB_PASSWORD", "yourpassword")

IMAGE_DIR = CONFIG.get("IMAGE_DIR", "/opt/vchanel/fastback/cam1_app_1/detected_frames")

MQTT_BROKER = CONFIG.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(CONFIG.get("MQTT_PORT", "1883"))

TOP_OPEN = CONFIG.get("MQTT_DASH_TOPIC_OPEN", "app/dashboard/open")
TOP_PUSH = CONFIG.get("MQTT_DASH_TOPIC_PUSH", "app/dashboard/data")

client = mqtt.Client()

active_sessions: dict[str, str] = {}
push_threads: dict[str, threading.Thread] = {}


# ===============================================================
# DB HELPERS
# ===============================================================

def fetch_today():
    query = """
        SELECT transaction_id, name, role, cam, vehicle_number,
               date, start_time, end_time,
               box_count, bale_count, bag_count, trolley_count,
               image_path
        FROM transaction_db
        WHERE date = CURRENT_DATE
        ORDER BY start_time ASC;
    """
    try:
        with psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        ) as conn:

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query)
                rows = cur.fetchall()

        result = []
        for r in rows:
            fname = os.path.basename(r["image_path"]) if r["image_path"] else None
            result.append({
                "transaction_id": r["transaction_id"],
                "name": r["name"],
                "role": r["role"],
                "camera": r["cam"],
                "vehicleNumber": r["vehicle_number"],
                "date": str(r["date"]),
                "startTime": str(r["start_time"]),
                "endTime": str(r["end_time"]),
                "box": r["box_count"],
                "bale": r["bale_count"],
                "bag": r["bag_count"],
                "trolley": r["trolley_count"],
                "imageUrl": f"http://192.168.1.7:9021/images/{fname}" if fname else None
            })
        return result

    except Exception as e:
        logger.error(f"DB ERROR (today): {e}", exc_info=True)
        return []


def fetch_last_7_days():
    query = """
        SELECT transaction_id, name, role, cam, vehicle_number,
               date, start_time, end_time,
               box_count, bale_count, bag_count, trolley_count,
               image_path
        FROM transaction_db
        WHERE date >= (
            SELECT MIN(date)
            FROM (
                SELECT DISTINCT date
                FROM transaction_db
                ORDER BY date DESC
                LIMIT 7
            ) q
        )
        ORDER BY date DESC;
    """
    try:
        with psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        ) as conn:

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query)
                rows = cur.fetchall()

        grouped = defaultdict(list)
        for r in rows:
            fname = os.path.basename(r["image_path"]) if r["image_path"] else None
            item = {
                "transaction_id": r["transaction_id"],
                "name": r["name"],
                "role": r["role"],
                "camera": r["cam"],
                "vehicleNumber": r["vehicle_number"],
                "date": str(r["date"]),
                "startTime": str(r["start_time"]),
                "endTime": str(r["end_time"]),
                "box": r["box_count"],
                "bale": r["bale_count"],
                "bag": r["bag_count"],
                "trolley": r["trolley_count"],
                "imageUrl": f"http://192.168.1.7:9021/images/{fname}" if fname else None
            }
            grouped[str(r["date"])].append(item)

        return grouped

    except Exception as e:
        logger.error(f"DB ERROR (history): {e}", exc_info=True)
        return {}


# ===============================================================
# PUSH LOOP
# ===============================================================

def push_loop(userId: str, sessionId: str):
    logger.info(f"Starting push loop for {userId}/{sessionId}")

    fail_count = 0
    out_topic = f"{TOP_PUSH}/{userId}/{sessionId}"

    while True:
        if active_sessions.get(userId) != sessionId:
            logger.info(f"Session changed → Stopping push for {userId}/{sessionId}")
            break

        today = fetch_today()
        history = fetch_last_7_days()

        payload = json.dumps({
            "today": today,
            "history": history
        })

        try:
            result = client.publish(out_topic, payload, qos=1)
            result.wait_for_publish()

            if result.is_published():
                fail_count = 0
                logger.debug(f"Sent update → {out_topic}")
            else:
                fail_count += 1
                logger.warning(f"Publish not confirmed ({fail_count}/3)")

        except Exception as e:
            fail_count += 1
            logger.error(f"Publish fail: {e}", exc_info=True)

        if fail_count >= 3:
            logger.warning(f"Stopping push after 3 failures for {userId}/{sessionId}")
            break

        time.sleep(3)


# ===============================================================
# MQTT CALLBACKS
# ===============================================================

def on_connect(client, userdata, flags, rc):
    logger.info(f"MQTT Connected with result code {rc}")
    client.subscribe(TOP_OPEN, qos=1)


def on_message(client, userdata, msg):
    payload = msg.payload.decode()
    logger.debug(f"MQTT Received: {msg.topic} → {payload}")

    try:
        data = json.loads(payload)
        userId = data.get("userId")
        sessionId = data.get("sessionId")
    except Exception:
        logger.error("Invalid MQTT JSON", exc_info=True)
        return

    if not userId or not sessionId:
        logger.error("Missing userId/sessionId in MQTT payload")
        return

    active_sessions[userId] = sessionId

    # Restart thread
    if userId in push_threads:
        logger.info(f"Restarting push thread for {userId}")

    t = threading.Thread(target=push_loop, args=(userId, sessionId), daemon=True)
    t.start()
    push_threads[userId] = t


client.on_connect = on_connect
client.on_message = on_message


def mqtt_thread():
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        logger.error(f"MQTT connection error: {e}", exc_info=True)


# Start MQTT in background
threading.Thread(target=mqtt_thread, daemon=True).start()


# ===============================================================
# SIMPLE HEALTH ENDPOINT
# ===============================================================

@router.get("/health")
def health():
    return {"status": "ok", "service": "dash-mqtt"}
