"""
cam1/main.py — CAM1 FastAPI Application
=========================================
Entry point for cam1 detection API (port 8000).
Starts all background services on startup.
Max 60 lines. One responsibility: app startup/shutdown.
"""

import sys
sys.path.insert(0, "/opt/secure_ai")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import getint, get, getbool
from core.logger import get_logger
from core.log_codes import get as LOG
from core.mqtt import publish_boot
from cam1.api.routes import router
from metrics.monitor import start as start_metrics
from scheduler.auto_start import start as start_auto
from scheduler.auto_stop import start as start_auto_stop
from scheduler.housekeeping import start as start_housekeeping

logger = get_logger("API")
PORT   = getint("CAM1_PORT", 8000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────
    logger.info(LOG("API.001.INFO", cam="cam1", port=PORT))
    logger.info(LOG("SYS.001.INFO"))

    # Close orphan open sessions from previous runs
    try:
        import psycopg2
        from core.config import get
        conn = psycopg2.connect(
            host=get("DB_HOST","localhost"), port=int(get("DB_PORT","5432")),
            user=get("DB_USER","kaai"), password=get("DB_PASSWORD","kaai123"),
            dbname=get("DB_NAME","jlmill")
        )
        cur = conn.cursor()
        cur.execute("""
            UPDATE transaction_db
            SET end_time = start_time
            WHERE date = CURRENT_DATE
              AND end_time IS NULL
              AND name = 'AutoStarter'
        """)
        closed = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Startup cleanup: closed orphan sessions → {closed}")
    except Exception as e:
        logger.warning(f"Startup cleanup failed: {e}")

    # Start background services
    start_metrics()
    start_auto()
    start_auto_stop()
    start_housekeeping()
    publish_boot("cam_1")

    logger.info(LOG("SYS.002.INFO"))
    yield

    # ── Shutdown ──────────────────────────────────────────────
    logger.info(LOG("SYS.003.INFO"))
    from metrics.monitor import stop as stop_metrics
    stop_metrics()


app = FastAPI(
    title="JL-CAM CAM1 Detection API",
    version="3.0.0",
    description="CAM1 live detection — MOG2 + YOLOX + ByteTrack",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get("CAM1_ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "cam1.main:app",
        host="0.0.0.0",
        port=PORT,
        log_level="warning",
    )
