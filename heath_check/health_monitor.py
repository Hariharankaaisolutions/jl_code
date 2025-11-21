import time
import json
import psycopg2
import paho.mqtt.client as mqtt
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import os

# ====================================================
# LOAD PROPERTIES
# ====================================================
def load_properties(filename):
    props = {}
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Properties file not found: {filename}")

    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#") and line != "":
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
    return props


# Load config from /config folder
CONFIG = load_properties("config/healthcheck.properties")

# MQTT
MQTT_HOST = CONFIG.get("MQTT_HOST", "localhost")
MQTT_PORT = int(CONFIG.get("MQTT_PORT", 1883))
MQTT_TOPIC = CONFIG.get("MQTT_TOPIC", "system/health_mqtt")

# Database
DB_NAME = CONFIG.get("DB_NAME", "test")
DB_USER = CONFIG.get("DB_USER", "postgres")
DB_PASS = CONFIG.get("DB_PASS", "123")
DB_HOST = CONFIG.get("DB_HOST", "localhost")
DB_PORT = int(CONFIG.get("DB_PORT", 5432))

# Logging
LOG_FILE = CONFIG.get("LOG_FILE", "heartbeat.log")

# FastAPI
FASTAPI_URL = CONFIG.get("FASTAPI_URL", "http://0.0.0.0:8000/status")
FASTAPI_TIMEOUT = int(CONFIG.get("FASTAPI_TIMEOUT", 3))


# ====================================================
# TIME (IST)
# ====================================================
def now_ist():
    return datetime.now(ZoneInfo("Asia/Kolkata"))


# ====================================================
# LOG WRITER
# ====================================================
def write_log(data):
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(data) + "\n")


# ====================================================
# MQTT HEALTH CHECK
# ====================================================
def check_mqtt():
    try:
        client = mqtt.Client()
        client.connect(MQTT_HOST, MQTT_PORT, 5)
        client.publish(MQTT_TOPIC, "alive")
        return True
    except Exception:
        return False


# ====================================================
# DATABASE HEALTH CHECK
# ====================================================
def check_db():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT,
            connect_timeout=3
        )
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        conn.close()
        return True
    except Exception:
        return False


# ====================================================
# FASTAPI HEALTH CHECK
# ====================================================
def check_fastapi():
    try:
        start = time.time()
        r = requests.get(FASTAPI_URL, timeout=FASTAPI_TIMEOUT)
        latency = round((time.time() - start) * 1000)  # ms

        if r.status_code == 200:
            return True, latency
        else:
            return False, latency
    except Exception:
        return False, None


# ====================================================
# MAIN LOOP
# ====================================================
def run():
    mqtt_timer = 0
    db_timer = 0
    api_timer = 0

    while True:
        now = time.time()
        heartbeat = {"timestamp": now_ist().isoformat()}

        # MQTT — every 10 seconds
        if now - mqtt_timer > 10:
            heartbeat["mqtt_ok"] = check_mqtt()
            mqtt_timer = now

        # DB — every 30 seconds
        if now - db_timer > 30:
            heartbeat["db_ok"] = check_db()
            db_timer = now

        # FASTAPI — every 10 seconds
        if now - api_timer > 10:
            api_ok, latency = check_fastapi()
            heartbeat["fastapi_ok"] = api_ok
            heartbeat["fastapi_latency_ms"] = latency
            api_timer = now

        #print(json.dumps(heartbeat, indent=2))
        write_log(heartbeat)

        time.sleep(1)


# ====================================================
# ENTRY POINT
# ====================================================
if __name__ == "__main__":
    run()
