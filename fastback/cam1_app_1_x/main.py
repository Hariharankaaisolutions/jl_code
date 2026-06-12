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
