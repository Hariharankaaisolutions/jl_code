# mqtt_control.py — MQTT Control Command Handler
# ================================================
# Subscribes to control topics from mobile app
# Handles: halt, resume, restart, status
#
# Topics (subscribe):
#   jlmill/control/halt    → stop session, disable auto-restart
#   jlmill/control/resume  → re-enable auto-restart
#   jlmill/control/restart → force restart session now
#   jlmill/control/status  → publish current system status
#
# Topics (publish):
#   jlmill/system/status   → system status response
#   jlmill/system/boot     → sent at boot
# ================================================

import json
import os
import asyncio
import psutil
from datetime import datetime
from typing import Optional, Callable

import paho.mqtt.client as mqtt

from jl_logger import get_logger

logger = get_logger("MQTT")

# ─────────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────────
_PROPS_FILE = os.path.join(os.path.dirname(__file__), "app.properties")

def _load_props() -> dict:
    props = {}
    try:
        with open(_PROPS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
    except Exception:
        pass
    return props

_props          = _load_props()
MQTT_HOST       = _props.get("MQTT_HOST",       "127.0.0.1")
MQTT_PORT       = int(_props.get("MQTT_PORT",   "1883"))
MQTT_TOPIC_BASE = _props.get("MQTT_TOPIC_BASE", "jlmill/sessions/")
MQTT_USERNAME   = _props.get("MQTT_USERNAME",   "")
MQTT_PASSWORD   = _props.get("MQTT_PASSWORD",   "")

# Control topics
TOPIC_HALT    = "jlmill/control/halt"
TOPIC_RESUME  = "jlmill/control/resume"
TOPIC_RESTART = "jlmill/control/restart"
TOPIC_STATUS  = "jlmill/control/status"

# Publish topics
TOPIC_SYS_STATUS = "jlmill/system/status"
TOPIC_SYS_BOOT   = "jlmill/system/boot"
TOPIC_SYS_ERROR  = "jlmill/system/error"

# ─────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────
_client: Optional[mqtt.Client]  = None
_halt_flag: bool                = False  # True = auto-restart disabled
_connected: bool                = False

# Callbacks registered by auto_start_session
_on_halt_cb:    Optional[Callable] = None
_on_resume_cb:  Optional[Callable] = None
_on_restart_cb: Optional[Callable] = None

def is_halted() -> bool:
    """Returns True if halt command was received — auto-restart disabled."""
    return _halt_flag

def register_callbacks(
    on_halt:    Optional[Callable] = None,
    on_resume:  Optional[Callable] = None,
    on_restart: Optional[Callable] = None,
):
    """Register callbacks for control commands."""
    global _on_halt_cb, _on_resume_cb, _on_restart_cb
    _on_halt_cb    = on_halt
    _on_resume_cb  = on_resume
    _on_restart_cb = on_restart
    logger.info("MQTT control callbacks registered")

# ─────────────────────────────────────────────────
# Status payload builder
# ─────────────────────────────────────────────────
def _build_status_payload() -> dict:
    """Build current system status payload."""
    try:
        cpu  = psutil.cpu_percent(interval=0.5)
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        def _proc_running(name_part: str) -> bool:
            for p in psutil.process_iter(["cmdline", "name"]):
                try:
                    cmd = " ".join(p.info.get("cmdline") or [])
                    if name_part in cmd or name_part in (p.info.get("name") or ""):
                        return True
                except Exception:
                    pass
            return False

        return {
            "timestamp":        datetime.now().isoformat(),
            "halt_active":      _halt_flag,
            "cpu_pct":          round(cpu, 1),
            "ram_used_pct":     mem.percent,
            "disk_free_gb":     round(disk.free / (1024**3), 1),
            "mediamtx_running": _proc_running("mediamtx"),
            "ffmpeg_cam1":      _proc_running("cam_1"),
            "cam1_api":         _proc_running("8000"),
        }
    except Exception as e:
        logger.error(f"build_status_payload failed: {e}", exc_info=True)
        return {"timestamp": datetime.now().isoformat(), "error": str(e)}


# ─────────────────────────────────────────────────
# MQTT callbacks
# ─────────────────────────────────────────────────
def _on_connect(client, userdata, flags, rc):
    global _connected
    if rc == 0:
        _connected = True
        # Subscribe to all control topics
        topics = [
            (TOPIC_HALT,    0),
            (TOPIC_RESUME,  0),
            (TOPIC_RESTART, 0),
            (TOPIC_STATUS,  0),
        ]
        client.subscribe(topics)
        logger.info(
            f"MQTT control connected. Subscribed to: "
            f"{TOPIC_HALT}, {TOPIC_RESUME}, {TOPIC_RESTART}, {TOPIC_STATUS}"
        )
        # Publish boot notification
        _publish_boot_notification(client)
    else:
        _connected = False
        logger.error(f"MQTT control connect failed rc={rc}")

def _on_disconnect(client, userdata, rc):
    global _connected
    _connected = False
    if rc != 0:
        logger.warning(f"MQTT control disconnected unexpectedly rc={rc} — will auto-reconnect")
    else:
        logger.info("MQTT control disconnected cleanly")

def _on_message(client, userdata, msg):
    global _halt_flag
    topic   = msg.topic
    payload = msg.payload.decode("utf-8", errors="replace").strip()

    logger.info(f"MQTT control received → topic={topic} payload={payload[:100]}")

    try:
        if topic == TOPIC_HALT:
            _halt_flag = True
            logger.warning(
                "HALT command received — auto-restart DISABLED. "
                "Send RESUME to re-enable."
            )
            if _on_halt_cb:
                _on_halt_cb()
            _publish_status(client, extra={"command": "halt", "result": "auto-restart disabled"})

        elif topic == TOPIC_RESUME:
            _halt_flag = False
            logger.info("RESUME command received — auto-restart RE-ENABLED")
            if _on_resume_cb:
                _on_resume_cb()
            _publish_status(client, extra={"command": "resume", "result": "auto-restart enabled"})

        elif topic == TOPIC_RESTART:
            logger.info("RESTART command received — forcing session restart")
            if _on_restart_cb:
                _on_restart_cb()
            _publish_status(client, extra={"command": "restart", "result": "restart triggered"})

        elif topic == TOPIC_STATUS:
            logger.info("STATUS request received — publishing system status")
            _publish_status(client)

        else:
            logger.warning(f"Unknown control topic: {topic}")

    except Exception as e:
        logger.error(f"MQTT control message handler error: {e}", exc_info=True)

def _on_publish(client, userdata, mid):
    logger.debug(f"MQTT published mid={mid}")


# ─────────────────────────────────────────────────
# Publish helpers
# ─────────────────────────────────────────────────
def _publish_status(client: mqtt.Client, extra: dict = None):
    try:
        payload = _build_status_payload()
        if extra:
            payload.update(extra)
        result = client.publish(TOPIC_SYS_STATUS, json.dumps(payload), qos=1)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Status published → {TOPIC_SYS_STATUS}")
        else:
            logger.error(f"Status publish failed rc={result.rc}")
    except Exception as e:
        logger.error(f"_publish_status failed: {e}", exc_info=True)

def _publish_boot_notification(client: mqtt.Client):
    try:
        payload = {
            "event":     "system_boot",
            "timestamp": datetime.now().isoformat(),
            "message":   "JL-CAM system started",
        }
        payload.update(_build_status_payload())
        result = client.publish(TOPIC_SYS_BOOT, json.dumps(payload), qos=1)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Boot notification published → {TOPIC_SYS_BOOT}")
        else:
            logger.error(f"Boot notification publish failed rc={result.rc}")
    except Exception as e:
        logger.error(f"_publish_boot_notification failed: {e}", exc_info=True)

def publish_error(error_code: str, message: str, severity: str = "high"):
    """Publish system-level error to MQTT."""
    try:
        if not _client or not _connected:
            return
        payload = {
            "timestamp":  datetime.now().isoformat(),
            "error_code": error_code,
            "message":    message,
            "severity":   severity,
        }
        _client.publish(TOPIC_SYS_ERROR, json.dumps(payload), qos=1)
        logger.warning(f"System error published → {error_code}: {message}")
    except Exception as e:
        logger.error(f"publish_error failed: {e}", exc_info=True)

def publish_status():
    """Publish current status — callable from anywhere."""
    if _client and _connected:
        _publish_status(_client)


# ─────────────────────────────────────────────────
# Connect and start
# ─────────────────────────────────────────────────
def start_mqtt_control():
    """
    Initialize MQTT control client.
    Separate from main mqtt_push client.
    Call once at FastAPI startup.
    """
    global _client
    try:
        _client = mqtt.Client(client_id="jlcam_control")
        _client.on_connect    = _on_connect
        _client.on_disconnect = _on_disconnect
        _client.on_message    = _on_message
        _client.on_publish    = _on_publish

        if MQTT_USERNAME and MQTT_PASSWORD:
            _client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            logger.info("MQTT control auth configured")

        # Auto-reconnect
        _client.reconnect_delay_set(min_delay=1, max_delay=30)

        _client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        _client.loop_start()

        logger.info(
            f"MQTT control client started → "
            f"{MQTT_HOST}:{MQTT_PORT}"
        )
        return True

    except Exception as e:
        logger.error(f"MQTT control start failed: {e}", exc_info=True)
        return False

