"""
metrics/monitor.py — System Metrics Monitor
=============================================
Main loop that collects metrics and checks thresholds.
Runs as background thread inside FastAPI startup.
Max 60 lines. One responsibility: run metrics loop.
"""

import time
import threading
import psutil

from core.config import getint, getbool
from core.logger import get_logger
from core.log_codes import get as LOG
from metrics.collector import collect
from metrics.alerter import check

logger  = get_logger("METRICS")
ENABLED  = getbool("METRICS_ENABLED", True)
INTERVAL = getint("METRICS_INTERVAL_SECS", 60)

_thread: threading.Thread = None
_stop   = threading.Event()


def _get_process_cpu(name: str) -> float:
    """Get CPU % of a named process."""
    try:
        for p in psutil.process_iter(["name", "cmdline", "cpu_percent"]):
            cmd = " ".join(p.info.get("cmdline") or [])
            if name.lower() in cmd.lower():
                return p.cpu_percent(interval=0.1)
    except Exception:
        pass
    return 0.0


def _loop() -> None:
    """Main metrics collection loop."""
    logger.info(LOG("MET.001.INFO", interval=INTERVAL))

    while not _stop.is_set():
        try:
            m = collect()
            if not m:
                time.sleep(INTERVAL)
                continue

            ffmpeg_cpu = _get_process_cpu("ffmpeg")
            mog2_buf   = 0  # updated by segment processor if needed

            logger.info(LOG("MET.002.INFO",
                cpu=m["cpu_pct"],
                ram=m["ram_used_gb"],
                gpu=m["gpu_util"],
                temp=m["gpu_temp"],
                disk=m["disk_free_gb"],
            ))
            logger.info(
                f"CPU={m['cpu_pct']}% TEMP={m['cpu_temp']}°C | "
                f"RAM={m['ram_used_gb']}GB ({m['ram_pct']}%) SWAP={m['swap_pct']}% | "
                f"GPU={m['gpu_util']}% MEM={m['gpu_mem_mb']}MB "
                f"TEMP={m['gpu_temp']}°C FAN={m['gpu_fan']}% PWR={m['gpu_power']}W | "
                f"DISK={m['disk_free_gb']}GB free ({m['disk_pct']}%) | "
                f"NET={m['net_mbps']}Mbps | FFmpeg={ffmpeg_cpu}%CPU"
            )

            check(m, mog2_pending=mog2_buf)

        except Exception as e:
            logger.error(LOG("MET.017.ERROR", error=e))

        _stop.wait(INTERVAL)


def start() -> None:
    """Start metrics monitor in background thread."""
    global _thread
    if not ENABLED:
        logger.info(LOG("MET.018.INFO"))
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="metrics_monitor", daemon=True)
    _thread.start()


def stop() -> None:
    """Stop metrics monitor."""
    _stop.set()
    if _thread:
        _thread.join(timeout=5)
