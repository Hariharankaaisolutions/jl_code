"""
metrics/collector.py — System Metrics Collector
=================================================
Reads all system metrics: CPU, RAM, GPU, Disk, Network, Process.
Returns a clean dict of current readings.
Max 100 lines. One responsibility: collect metrics.
"""

import os
import time
import psutil
from typing import Optional

from core.logger import get_logger
from core.log_codes import get as LOG

logger = get_logger("METRICS")

# ── GPU via pynvml ─────────────────────────────────────────────
try:
    import pynvml
    pynvml.nvmlInit()
    _GPU_AVAILABLE = True
except Exception:
    _GPU_AVAILABLE = False

# ── Network baseline ───────────────────────────────────────────
_net_last     = psutil.net_io_counters()
_net_last_time = time.time()


def _gpu_metrics() -> dict:
    if not _GPU_AVAILABLE:
        return {"util": 0, "mem_used": 0, "mem_total": 0,
                "temp": 0, "fan": 0, "power": 0}
    try:
        h    = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        mem  = pynvml.nvmlDeviceGetMemoryInfo(h)
        temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        try:
            fan = pynvml.nvmlDeviceGetFanSpeed(h)
        except Exception:
            fan = 0
        try:
            power = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
        except Exception:
            power = 0
        return {
            "util":      util.gpu,
            "mem_used":  mem.used / 1024 / 1024,
            "mem_total": mem.total / 1024 / 1024,
            "temp":      temp,
            "fan":       fan,
            "power":     round(power, 1),
        }
    except Exception as e:
        logger.error(LOG("MET.017.ERROR", error=e))
        return {"util": 0, "mem_used": 0, "mem_total": 0,
                "temp": 0, "fan": 0, "power": 0}


def _cpu_temp() -> float:
    try:
        temps = psutil.sensors_temperatures()
        for key in ("coretemp", "cpu_thermal", "k10temp"):
            if key in temps:
                entries = temps[key]
                if entries:
                    return round(entries[0].current, 1)
    except Exception:
        pass
    return 0.0


def _net_bandwidth() -> float:
    global _net_last, _net_last_time
    try:
        now      = time.time()
        counters = psutil.net_io_counters()
        elapsed  = now - _net_last_time
        if elapsed <= 0:
            return 0.0
        sent  = (counters.bytes_sent - _net_last.bytes_sent) / elapsed
        recv  = (counters.bytes_recv - _net_last.bytes_recv) / elapsed
        _net_last      = counters
        _net_last_time = now
        return round((sent + recv) / 1024 / 1024, 2)
    except Exception:
        return 0.0


def collect() -> dict:
    """Collect all system metrics. Returns dict."""
    try:
        cpu     = psutil.cpu_percent(interval=1)
        cpu_tmp = _cpu_temp()
        ram     = psutil.virtual_memory()
        swap    = psutil.swap_memory()
        disk    = psutil.disk_usage("/")
        gpu     = _gpu_metrics()
        net_mbps = _net_bandwidth()

        return {
            "cpu_pct":      round(cpu, 1),
            "cpu_temp":     cpu_tmp,
            "ram_used_gb":  round(ram.used / 1e9, 2),
            "ram_pct":      round(ram.percent, 1),
            "swap_pct":     round(swap.percent, 1),
            "disk_free_gb": round(disk.free / 1e9, 1),
            "disk_pct":     round(disk.percent, 1),
            "net_mbps":     net_mbps,
            "gpu_util":     gpu["util"],
            "gpu_mem_mb":   round(gpu["mem_used"], 0),
            "gpu_mem_pct":  round(gpu["mem_used"] / max(gpu["mem_total"], 1) * 100, 1),
            "gpu_temp":     gpu["temp"],
            "gpu_fan":      gpu["fan"],
            "gpu_power":    gpu["power"],
        }
    except Exception as e:
        logger.error(LOG("MET.017.ERROR", error=e))
        return {}
