"""
core/mqtt.py — MQTT Client
============================
Handles all MQTT publish operations for JL-CAM.
Reads config from master.properties.
Max 80 lines. One responsibility: MQTT publish.
"""

import json
import threading
from datetime import datetime
from typing import Optional

import paho.mqtt.client as mqtt

from core.config import get, getint, getbool
from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("MQTT")

# ── Config ─────────────────────────────────────────────────────
ENABLED     = getbool("MQTT_ENABLED", True)
HOST        = get("MQTT_HOST",  "127.0.0.1")
PORT        = getint("MQTT_PORT", 1883)
TOPIC_BASE  = get("MQTT_TOPIC_BASE",  "jlmill/sessions/")
TOPIC_BOOT  = get("MQTT_TOPIC_BOOT",  "jlmill/system/boot")
TOPIC_ALERT = get("MQTT_TOPIC_ALERT", "jlmill/system/alert")
TOPIC_COUNT = get("MQTT_TOPIC_COUNTS", "jl/counts")

# ── Client ─────────────────────────────────────────────────────
_client: Optional[mqtt.Client] = None
_lock = threading.Lock()


def _get_client() -> Optional[mqtt.Client]:
    global _client
    if _client and _client.is_connected():
        return _client
    try:
        c = mqtt.Client()

        def on_connect(c, u, f, rc):
            if rc == 0:
                logger.info(LOG("MQTT.001.INFO", host=HOST, port=PORT))
            else:
                logger.error(LOG("MQTT.002.ERROR", error=f"rc={rc}"))

        def on_disconnect(c, u, rc):
            logger.warning(LOG("MQTT.003.WARN", rc=rc))

        c.on_connect    = on_connect
        c.on_disconnect = on_disconnect
        c.connect(HOST, PORT, 60)
        c.loop_start()
        _client = c
        return _client
    except Exception as e:
        logger.error(LOG("MQTT.002.ERROR", error=e))
        return None


def publish(topic: str, payload: dict) -> bool:
    if not ENABLED:
        return True
    try:
        client = _get_client()
        if not client:
            return False
        with _lock:
            client.publish(topic, json.dumps(payload), qos=0, retain=False)
        logger.info(LOG("MQTT.005.INFO", topic=topic))
        return True
    except Exception as e:
        logger.error(LOG("MQTT.006.ERROR", topic=topic, error=e))
        return False


def publish_boot(cam: str = "cam_1") -> None:
    publish(TOPIC_BOOT, {
        "cam": cam, "event": "boot",
        "time": datetime.now().isoformat()
    })
    logger.info(LOG("MQTT.007.INFO"))


def publish_counts(session_id: str, transaction_id: str, counts: dict) -> None:
    publish(f"{TOPIC_BASE}{session_id}/{transaction_id}/counts", {
        "session_id": session_id,
        "transaction_id": transaction_id,
        "counts": counts,
        "time": datetime.now().isoformat()
    })
    logger.info(LOG("MQTT.008.INFO", session_id=session_id[:8]))


def publish_alert(code: str, message: str, severity: str = "high") -> None:
    publish(TOPIC_ALERT, {
        "code": code, "message": message,
        "severity": severity,
        "time": datetime.now().isoformat()
    })
    logger.info(LOG("MQTT.010.INFO", code=code))
