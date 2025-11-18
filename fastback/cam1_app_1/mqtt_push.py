# mqtt_push.py — Fully Converted to Message Codes
# ===============================================

from smart_logger import get_logger
logger = get_logger(__name__)

from message_loader import Messages   # <-- NEW

import json
import paho.mqtt.client as mqtt
from config_loader import MQTT_HOST, MQTT_PORT, MQTT_TOPIC_BASE, MQTT_USERNAME, MQTT_PASSWORD


# ---------------------------------------------------------
# MQTT Configuration
# ---------------------------------------------------------
MQTT_BROKER = MQTT_HOST
MQTT_PORT = MQTT_PORT
MQTT_TOPIC_BASE = MQTT_TOPIC_BASE
MQTT_USERNAME = MQTT_USERNAME
MQTT_PASSWORD = MQTT_PASSWORD

client = mqtt.Client()


# ---------------------------------------------------------
# AUTH SETUP
# ---------------------------------------------------------
if MQTT_USERNAME and MQTT_PASSWORD:
    logger.info(Messages.get("MQTT.CONFIG.001.INFO"))
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
else:
    logger.warning(Messages.get("MQTT.CONFIG.002.WARN"))


# =====================================================================
# CALLBACKS
# =====================================================================
def _on_connect(client, userdata, flags, rc):
    logger.info(Messages.get("MQTT.CONNECT.001.INFO", rc=rc))
    if rc != 0:
        logger.error(Messages.get("MQTT.CONNECT.002.ERROR", rc=rc))


def _on_disconnect(client, userdata, rc):
    logger.warning(Messages.get("MQTT.CONNECT.003.WARN", rc=rc))


def _on_publish(client, userdata, mid):
    logger.debug(Messages.get("MQTT.PUBLISH.001.DEBUG", mid=mid))


client.on_connect = _on_connect
client.on_disconnect = _on_disconnect
client.on_publish = _on_publish


# =====================================================================
# CONNECT
# =====================================================================
def mqtt_connect():
    logger.info(Messages.get("MQTT.CONNECT.004.INFO"))
    logger.debug(
        Messages.get(
            "MQTT.CONFIG.003.DEBUG",
            host=MQTT_BROKER,
            port=MQTT_PORT,
            username=MQTT_USERNAME or "none"
        )
    )

    try:
        logger.debug(Messages.get("MQTT.CONNECT.006.DEBUG"))
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

        logger.debug(Messages.get("MQTT.CONNECT.007.DEBUG"))
        client.loop_start()

        logger.info(Messages.get("MQTT.CONNECT.004.INFO"))

    except Exception:
        logger.exception(Messages.get("MQTT.CONNECT.005.ERROR"))


# =====================================================================
# MQTT PUBLISH COUNTS
# =====================================================================
def mqtt_push_counts(session_id, transaction_id, counts: dict):
    topic = f"{MQTT_TOPIC_BASE}{session_id}/{transaction_id}/counts"

    logger.debug(
        Messages.get(
            "MQTT.PUBLISH.002.DEBUG",
            topic=topic,
            session_id=session_id,
            transaction_id=transaction_id,
            counts=counts
        )
    )

    try:
        payload = json.dumps({
            "session_id": session_id,
            "transaction_id": transaction_id,
            "counts": counts
        })

        logger.debug(Messages.get("MQTT.PUBLISH.006.DEBUG", payload=payload))

        result = client.publish(topic, payload)

        logger.debug(
            Messages.get(
                "MQTT.PUBLISH.007.DEBUG",
                rc=result.rc,
                mid=result.mid
            )
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(Messages.get("MQTT.PUBLISH.003.INFO", topic=topic))
        else:
            logger.error(
                Messages.get(
                    "MQTT.PUBLISH.004.ERROR",
                    rc=result.rc,
                    topic=topic
                )
            )

    except Exception:
        logger.exception(
            Messages.get("MQTT.PUBLISH.005.ERROR", topic=topic)
        )


# =====================================================================
# MQTT ERROR PUBLISH
# =====================================================================
def mqtt_push_error(session_id, transaction_id, error_code, message, severity="medium"):
    topic = f"{MQTT_TOPIC_BASE}{session_id}/{transaction_id}/error"

    logger.debug(
        Messages.get(
            "MQTT.ERROR.001.DEBUG",
            topic=topic,
            session_id=session_id,
            transaction_id=transaction_id,
            error_code=error_code,
            severity=severity
        )
    )

    try:
        payload = json.dumps({
            "session_id": session_id,
            "transaction_id": transaction_id,
            "error_code": error_code,
            "message": message,
            "severity": severity
        })

        result = client.publish(topic, payload)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.warning(
                Messages.get("MQTT.ERROR.002.WARN", error_code=error_code, message=message)
            )
        else:
            logger.error(
                Messages.get(
                    "MQTT.ERROR.003.ERROR",
                    rc=result.rc,
                    topic=topic
                )
            )

    except Exception:
        logger.exception(
            Messages.get("MQTT.ERROR.004.ERROR", topic=topic)
        )
