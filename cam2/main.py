"""
cam2/main.py — CAM2 FastAPI Application
=========================================
Entry point for cam2 detection API (port 8001).
Bag detection: bag, 2bag, 3bag, 4bag, trolley.
Max 60 lines. One responsibility: app startup/shutdown.
"""

import sys
sys.path.insert(0, "/opt/secure_ai")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import getint, get
from core.logger import get_logger
from core.log_codes import get as LOG
from cam2.api.routes import router

logger = get_logger("API")
PORT   = getint("CAM2_PORT", 8001)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(LOG("API.001.INFO", cam="cam2", port=PORT))
    logger.info(LOG("SYS.001.INFO"))
    logger.info(LOG("SYS.002.INFO"))
    yield
    logger.info(LOG("SYS.003.INFO"))


app = FastAPI(
    title="JL-CAM CAM2 Detection API",
    version="3.0.0",
    description="CAM2 bag detection — MOG2 + YOLOX + ByteTrack",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "cam2.main:app",
        host="0.0.0.0",
        port=PORT,
        log_level="warning",
    )
