# linux_publisher_full.py
from fastapi import FastAPI
import psycopg2
import paho.mqtt.publish as publish
import paho.mqtt.client as mqtt
import json
import time
import threading
import base64
import os

app = FastAPI()

# ---------------------- CONFIG ---------------------- #
# PostgreSQL Config (Linux)
DB_CONFIG = {
    "host": "localhost",
    "database": "jlmill",
    "user": "kaai",
    "password": "yourpassword"
}

# MQTT Broker (Windows)
MQTT_BROKER = "192.168.1.6"   # Windows IP or Broker IP
MQTT_PORT = 1883
TRANSACTION_TOPIC = "transaction/sync"
REQUEST_TOPIC = "image/request"
RESPONSE_TOPIC = "image/response"

# Track last sync time
last_sync_time = None


# ---------------------- DATABASE ---------------------- #
def get_connection():
    """Create and return PostgreSQL connection"""
    return psycopg2.connect(**DB_CONFIG)


def sync_to_cloud():
    """Read new/updated transactions and publish to MQTT broker"""
    global last_sync_time
    conn = get_connection()
    cur = conn.cursor()

    # Fetch new or updated records
    if last_sync_time:
        cur.execute("SELECT * FROM transaction_db WHERE updated_at > %s", (last_sync_time,))
    else:
        # On first run, send all records
        cur.execute("SELECT * FROM transaction_db")

    rows = cur.fetchall()
    colnames = [desc[0] for desc in cur.description]

    # Publish each record to MQTT
    for row in rows:
        record = dict(zip(colnames, row))
        message = json.dumps(record, default=str)
        publish.single(TRANSACTION_TOPIC, message, hostname=MQTT_BROKER, port=MQTT_PORT)
        print(f"📤 Published transaction {record['transaction_id']}")

    # Update last sync time
    last_sync_time = time.strftime('%Y-%m-%d %H:%M:%S')

    cur.close()
    conn.close()

    return len(rows)


# ---------------------- IMAGE HANDLER ---------------------- #
def on_message(client, userdata, msg):
    """Triggered when subscriber requests an image"""
    image_path = msg.payload.decode()
    print(f"📥 Received image request for: {image_path}")

    if not os.path.exists(image_path):
        client.publish(RESPONSE_TOPIC, "ERROR: File not found")
        print("❌ ERROR: File not found")
        return

    try:
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        client.publish(RESPONSE_TOPIC, image_data)
        print(f"📤 Sent image data to {RESPONSE_TOPIC}")
    except Exception as e:
        print(f"⚠️ Error sending image: {e}")
        client.publish(RESPONSE_TOPIC, f"ERROR: {e}")


def start_image_listener():
    """Start a separate MQTT client to handle image requests"""
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.subscribe(REQUEST_TOPIC)
    print(f"🖼️ Listening for image requests on topic: {REQUEST_TOPIC}")
    client.loop_forever()


# ---------------------- BACKGROUND TASKS ---------------------- #
def background_sync():
    """Perform initial and periodic sync"""
    print("🚀 Performing initial full sync...")
    total = sync_to_cloud()
    print(f"✅ Initial sync completed — {total} records sent.")

    # Optional: continuous sync every 60 seconds
    while True:
        time.sleep(60)
        total = sync_to_cloud()
        if total > 0:
            print(f"🔁 Synced {total} new/updated records.")


@app.on_event("startup")
def on_startup():
    """Automatically run once when the server starts"""
    threading.Thread(target=background_sync, daemon=True).start()
    threading.Thread(target=start_image_listener, daemon=True).start()


# ---------------------- API ROUTES ---------------------- #
@app.get("/")
def home():
    return {"status": "publisher running", "broker": MQTT_BROKER}


@app.get("/sync")
def manual_sync():
    """Manual trigger for sync"""
    total = sync_to_cloud()
    return {"status": "success", "message": f"{total} records pushed to MQTT"}


# ---------------------- RUN ---------------------- #
# Run this app:
# uvicorn linux_publisher_full:app --host 0.0.0.0 --port 9000
