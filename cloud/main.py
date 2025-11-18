# main.py

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from utils_config_loader import load_properties
from logger import get_logger

# Routers
from modules.camera_backend import router as camera_router
from modules.dash import router as dash_router
from modules.dashboard import router as dashboard_router
from modules.dbhost import router as dbhost_router
from modules.registration import router as registration_router
from modules.session import router as session_router
from modules.webdata import router as webdata_router

CONFIG = load_properties("config.properties")
logger = get_logger("main")

app = FastAPI(
    title="JLMill Unified Backend",
    version="3.0.0",
    description="Unified FastAPI backend combining camera, dashboard, registration, session and DB APIs."
)

# CORS – allow all for now (you can restrict to specific domains)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files mount for images (used by dashboards)
IMAGE_DIR = CONFIG.get("IMAGE_DIR")
if IMAGE_DIR and os.path.exists(IMAGE_DIR):
    app.mount("/images", StaticFiles(directory=IMAGE_DIR), name="images")
    logger.info(f"Mounted /images from {IMAGE_DIR}")
else:
    logger.warning("IMAGE_DIR not set or path does not exist. /images not mounted.")


# Include all routers (no prefixes to keep paths similar to original)
app.include_router(camera_router)
app.include_router(dash_router)
app.include_router(dashboard_router)
app.include_router(dbhost_router)
app.include_router(registration_router)
app.include_router(session_router)
app.include_router(webdata_router)


@app.get("/")
def root():
    return {"status": "ok", "message": "JLMill Unified Backend Active"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
