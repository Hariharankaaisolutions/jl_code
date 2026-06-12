# modules/dashboard.py

from fastapi import APIRouter
from fastapi.middleware.cors import CORSMiddleware  # Not used directly, main handles CORS
from fastapi import Depends
from fastapi.staticfiles import StaticFiles  # Not used here, static served in main
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

router = APIRouter(tags=["Dashboard REST + MQTT"])
logger = get_logger("dashboard")

CONFIG = load_properties("config.properties")

DB_HOST = CONFIG.get("DB_HOST", "localhost")
DB_NAME = CONFIG.get("DB_NAME", "jlmill")
DB_USER = CONFIG.get("DB_USER", "kaai")
DB_PASS = CONFIG.get("DB_PASSWORD", "yourpassword")

IMAGE_DIR = CONFIG.get("IMAGE_DIR", "/opt/vchanel/fastback/database/detected_frames")

# ✅ NEW externalised image base URL
IMAGE_BASE_URL = CONFIG.get("IMAGE_BASE_URL", "http://localhost:9000/images")

MQTT_BROKER = CONFIG.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(CONFIG.get("MQTT_PORT", "1883"))
MQTT_TOPIC_REQUEST = CONFIG.get("MQTT_DASHBOARD_REQUEST", "vchanel/loading/request")
MQTT_TOPIC_RESPONSE = CONFIG.get("MQTT_DASHBOARD_RESPONSE", "vchanel/loading/response")

latest_data = []  # Cached data for MQTT responses

client = mqtt.Client()


# ---------------------------------------------------------------
# Helper: raw image_path column value → list of full image URLs
#
# Handles all three possible formats stored in the DB:
#   None / ""                   → []
#   JSON array string (new)     → '["path/a.jpg","path/b.jpg"]'
#   Plain single string (legacy)→ "path/a.jpg"
# ---------------------------------------------------------------
def build_image_urls(raw_image_path) -> list:
    if not raw_image_path:
        return []

    value = str(raw_image_path).strip()

    # ── new multi-image format ───────────────────────────────────
    if value.startswith("["):
        try:
            paths = json.loads(value)
            return [
                f"{IMAGE_BASE_URL}/{os.path.basename(p)}"
                for p in paths if p
            ]
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse image_path JSON: {value!r}")
            return []

    # ── legacy single-path string ────────────────────────────────
    filename = os.path.basename(value)
    return [f"{IMAGE_BASE_URL}/{filename}"] if filename else []


def fetch_data_from_postgres():
    """
    Returns last 7 unique dates of data, ordered by date desc.
    """
    query = """
        SELECT transaction_id, session_id, user_id, name, role, cam, vehicle_number,
               date, start_time, end_time, box_count, bale_count, bag_count, trolley_count,
               image_path, updated_at
        FROM transaction_db
        WHERE date >= (
            SELECT MIN(date)
            FROM (
                SELECT DISTINCT date
                FROM transaction_db
                ORDER BY date DESC
                LIMIT 7
            ) AS recent_dates
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
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query)
                results = cursor.fetchall()

                data = []
                for r in results:
                    image_urls = build_image_urls(r["image_path"])
                    data.append({
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
                        # ✅ multiple images (new)
                        "imageUrls": image_urls,
                        # ✅ first image kept for backwards compat
                        "imageUrl": image_urls[0] if image_urls else None,
                    })
                return data
    except Exception as e:
        logger.error(f"Database Error in fetch_data_from_postgres: {e}", exc_info=True)
        return []


def fetch_latest_transaction():
    query = """
        SELECT transaction_id, session_id, user_id, name, role, cam, vehicle_number,
        date, start_time, end_time, box_count, bale_count, bag_count, trolley_count, image_path, updated_at
        FROM transaction_db
        ORDER BY updated_at DESC
        LIMIT 1;
    """
    try:
        with psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        ) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query)
                record = cursor.fetchone()

                if not record:
                    return {}

                image_urls = build_image_urls(record["image_path"])
                return {
                    "transaction_id": record["transaction_id"],
                    "name": record["name"],
                    "role": record["role"],
                    "camera": record["cam"],
                    "vehicleNumber": record["vehicle_number"],
                    "date": str(record["date"]),
                    "startTime": str(record["start_time"]),
                    "endTime": str(record["end_time"]),
                    "box": record["box_count"],
                    "bale": record["bale_count"],
                    "bag": record["bag_count"],
                    "trolley": record["trolley_count"],
                    # ✅ multiple images (new)
                    "imageUrls": image_urls,
                    # ✅ first image kept for backwards compat
                    "imageUrl": image_urls[0] if image_urls else None,
                }
    except Exception as e:
        logger.error(f"Database Error in fetch_latest_transaction: {e}", exc_info=True)
        return {}


@router.get("/api/transactions/today")
async def fetch_today_transactions():
    """Fetch all transactions for the current date."""
    query = """
        SELECT transaction_id, session_id, user_id, name, role, cam, vehicle_number,
               date, start_time, end_time, box_count, bale_count, bag_count, trolley_count, image_path, updated_at
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
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
                data = []
                for r in results:
                    image_urls = build_image_urls(r["image_path"])
                    data.append({
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
                        # ✅ multiple images (new)
                        "imageUrls": image_urls,
                        # ✅ first image kept for backwards compat
                        "imageUrl": image_urls[0] if image_urls else None,
                    })
                return data
    except Exception as e:
        logger.error(f"Database Error in fetch_today_transactions: {e}", exc_info=True)
        return []


# MQTT callbacks

def on_connect(client, userdata, flags, rc):
    logger.info(f"Dashboard MQTT connected with code {rc}")
    client.subscribe(MQTT_TOPIC_REQUEST)


def on_message(client, userdata, msg):
    global latest_data
    try:
        if msg.topic == MQTT_TOPIC_REQUEST:
            data = fetch_data_from_postgres()
            latest_data = data
            client.publish(MQTT_TOPIC_RESPONSE, json.dumps(data))
            logger.info(f"Published {len(data)} records to {MQTT_TOPIC_RESPONSE}")
    except Exception as e:
        logger.error(f"MQTT on_message error: {e}", exc_info=True)


client.on_connect = on_connect
client.on_message = on_message


def mqtt_thread_func():
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        logger.error(f"Dashboard MQTT connection error: {e}", exc_info=True)


mqtt_thread = threading.Thread(target=mqtt_thread_func, daemon=True)
mqtt_thread.start()


# API routes

@router.get("/api/transactions")
async def get_latest_transactions():
    return latest_data or []


@router.get("/api/transactions/latest")
async def get_latest_transaction_route():
    """Fetch the latest transaction directly from database."""
    return fetch_latest_transaction()


@router.get("/publish-request")
async def publish_request():
    client.publish(MQTT_TOPIC_REQUEST, "request_data")
    time.sleep(1)
    return {"status": "request published", "data_count": len(latest_data)}


@router.get("/api/transactions/grouped")
async def fetch_data_grouped():
    """Fetch and group last 7 available unique dates' transactions."""
    data = fetch_data_from_postgres()

    if not data:
        return {"error": "No data found"}

    grouped = defaultdict(list)
    for record in data:
        grouped[record["date"]].append({
            "transaction_id": record["transaction_id"],
            "name": record["name"],
            "role": record["role"],
            "camera": record["camera"],
            "vehicleNumber": record["vehicleNumber"],
            "startTime": record["startTime"],
            "endTime": record["endTime"],
            "box": record["box"],
            "bale": record["bale"],
            "bag": record["bag"],
            "trolley": record["trolley"],
            # ✅ multiple images (new)
            "imageUrls": record["imageUrls"],
            # ✅ first image kept for backwards compat
            "imageUrl": record["imageUrl"],
        })

    return grouped