# modules/mqtt_test.py

import paho.mqtt.client as mqtt

from utils_config_loader import load_properties
from logger import get_logger

logger = get_logger("mqtt_test")
CONFIG = load_properties("config.properties")

MQTT_BROKER = CONFIG.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(CONFIG.get("MQTT_PORT", "1883"))
MQTT_TOPIC = "jlmill/sessions/#"   # subscribe to all sessions


def on_connect(client, userdata, flags, rc):
    logger.info(f"Connected to MQTT broker with code {rc}")
    client.subscribe(MQTT_TOPIC)
    logger.info(f"Subscribed to: {MQTT_TOPIC}")


def on_message(client, userdata, msg):
    logger.info(f"MQTT MESSAGE RECEIVED Topic={msg.topic} Payload={msg.payload.decode()}")


def start_mqtt_test_listener():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    start_mqtt_test_listener()
