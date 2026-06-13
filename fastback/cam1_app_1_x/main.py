# main.py — YOLOv5 Detection Backend (REFactored Entry Point)
# ==========================================================

# 🔴 IMPORTANT: smart_logger MUST be imported first
from smart_logger import get_logger
logger = get_logger(__name__)

# Keep logging import for compatibility
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# MQTT
from mqtt_push import mqtt_connect

# Messages
from message_loader import Messages

from auto_stop_scheduler import start_auto_stop_scheduler
from main_config import FASTAPI_TITLE, ALLOWED_ORIGINS, HOST, PORT


# API router (ALL endpoints inside)
from main_api import router as api_router


# ----------------------------------------------------------
# FastAPI App
# ----------------------------------------------------------
app = FastAPI(title=FASTAPI_TITLE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------
# Startup Event
# ----------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """
    Application startup:
    - Initialize MQTT
    - Log startup status
    """
    logger.info(Messages.get("API.STARTUP.001.INFO"))

    try:
        mqtt_connect()
        logger.info(Messages.get("API.STARTUP.002.INFO"))
    except Exception:
        logger.exception(Messages.get("API.STARTUP.003.ERROR"))

@app.on_event("startup")
async def startup():
    start_auto_stop_scheduler()

    # ── Unified logger boot message ───────────────────────────────────────────
    from jl_logger import get_logger as jl_get_logger, log_separator
    _boot_logger = jl_get_logger("SYSTEM")
    import platform, psutil
    log_separator("SYSTEM", "JL-CAM SYSTEM STARTING")
    _boot_logger.info(
        f"Boot → kernel={platform.uname().release} "
        f"python={platform.python_version()} "
        f"cpu_cores={psutil.cpu_count()} "
        f"ram={round(psutil.virtual_memory().total/(1024**3),1)}GB"
    )

    # ── System metrics monitor (CPU/RAM/disk/GPU every 60s) ───────────────────
    try:
        from system_metrics import start_metrics_monitor
        from alert_manager import alert_cpu_spike, alert_cpu_normal, alert_disk_low

        def _on_cpu_spike(cpu_pct):
            alert_cpu_spike(cpu_pct)

        def _on_cpu_normal(cpu_pct):
            alert_cpu_normal(cpu_pct)

        def _on_disk_low(free_gb):
            alert_disk_low(free_gb)

        start_metrics_monitor(
            on_spike=_on_cpu_spike,
            on_normal=_on_cpu_normal,
            on_disk_low=_on_disk_low,
        )
        _boot_logger.info("System metrics monitor started")
    except Exception:
        _boot_logger.exception("Failed to start system metrics monitor")

    # ── MQTT control (halt/resume/restart/status) ─────────────────────────────
    try:
        from mqtt_control import start_mqtt_control
        start_mqtt_control()
        _boot_logger.info("MQTT control handler started")
    except Exception:
        _boot_logger.exception("Failed to start MQTT control handler")

    # ── Auto-session manager (wait 10min then start session) ──────────────────
    try:
        from auto_start_session import start_auto_session
        start_auto_session()
        _boot_logger.info("Auto-session manager started")
    except Exception:
        _boot_logger.exception("Failed to start auto-session manager")

    log_separator("SYSTEM", "JL-CAM STARTUP COMPLETE")


# ----------------------------------------------------------
# Register API Routes
# ----------------------------------------------------------
app.include_router(api_router)


# ----------------------------------------------------------
# Entry Point
# ----------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    logger.info(
        Messages.get(
            "SERVER.UVICORN.001.INFO",
            host=HOST,
            port=PORT,
        )
    )

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info"
    )
