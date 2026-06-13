# system_metrics.py — System Metrics Monitor
# ===========================================
# Runs as background asyncio task inside CAM1 API
# Logs CPU, RAM, disk, GPU, FFmpeg process stats
# every 60 seconds to unified log
# Also detects CPU spikes > threshold and fires callback
# ===========================================

import asyncio
import os
import psutil
import time
from datetime import datetime
from typing import Optional, Callable

from jl_logger import get_logger

logger = get_logger("HEALTH")

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
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
    except Exception:
        pass
    return props

_props              = _load_props()
METRICS_INTERVAL    = int(_props.get("METRICS_INTERVAL_SECS", "60"))
CPU_THRESHOLD       = float(_props.get("INFERENCE_CPU_THRESHOLD", "80"))
GPU_THRESHOLD       = float(_props.get("INFERENCE_GPU_THRESHOLD", "90"))
VIDEO_SAVE_DIR      = _props.get("VIDEO_SAVE_DIR",
                       "/opt/secure_ai/fastback/cam1_app_1_x/detection_videos")

# ─────────────────────────────────────────────────
# GPU metrics via nvidia-smi
# ─────────────────────────────────────────────────
def _get_gpu_metrics() -> dict:
    """Get GPU utilization and memory via nvidia-smi."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) >= 5:
                return {
                    "gpu_util_pct":    float(parts[0]),
                    "gpu_mem_util_pct": float(parts[1]),
                    "gpu_mem_used_mb":  float(parts[2]),
                    "gpu_mem_total_mb": float(parts[3]),
                    "gpu_temp_c":       float(parts[4]),
                }
    except Exception:
        pass
    return {
        "gpu_util_pct": -1,
        "gpu_mem_util_pct": -1,
        "gpu_mem_used_mb": -1,
        "gpu_mem_total_mb": -1,
        "gpu_temp_c": -1,
    }

# ─────────────────────────────────────────────────
# FFmpeg process stats
# ─────────────────────────────────────────────────
def _get_ffmpeg_stats() -> dict:
    """Get CPU usage of running FFmpeg processes."""
    stats = {}
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline", "cpu_percent"]):
            try:
                if proc.info["name"] == "ffmpeg":
                    cmd = " ".join(proc.info["cmdline"] or [])
                    cpu = proc.cpu_percent(interval=0.1)
                    if "cam_1" in cmd or "cam1" in cmd:
                        stats["ffmpeg_cam1_cpu_pct"] = round(cpu, 1)
                    elif "cam_2" in cmd or "cam2" in cmd:
                        stats["ffmpeg_cam2_cpu_pct"] = round(cpu, 1)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass
    return stats

# ─────────────────────────────────────────────────
# Disk stats
# ─────────────────────────────────────────────────
def _get_disk_stats() -> dict:
    """Get disk usage for video save directory and root."""
    try:
        try:
            usage = psutil.disk_usage(VIDEO_SAVE_DIR)
        except Exception:
            usage = psutil.disk_usage("/")
        return {
            "disk_total_gb":  round(usage.total / (1024**3), 1),
            "disk_used_gb":   round(usage.used  / (1024**3), 1),
            "disk_free_gb":   round(usage.free  / (1024**3), 1),
            "disk_used_pct":  usage.percent,
        }
    except Exception:
        return {}

# ─────────────────────────────────────────────────
# MOG2 buffer stats
# ─────────────────────────────────────────────────
def _get_buffer_stats() -> dict:
    """Count pending frames in MOG2 buffer."""
    try:
        buffer_dir = _props.get(
            "MOG2_BUFFER_DIR",
            "/opt/secure_ai/fastback/cam1_app_1_x/detection_videos/mog2_buffer"
        )
        if not os.path.exists(buffer_dir):
            return {"mog2_buffer_pending": 0}
        count = 0
        for root, dirs, files in os.walk(buffer_dir):
            count += sum(1 for f in files if f.endswith(".jpg"))
        return {"mog2_buffer_pending": count}
    except Exception:
        return {"mog2_buffer_pending": -1}

# ─────────────────────────────────────────────────
# Single snapshot — collect all metrics
# ─────────────────────────────────────────────────
def collect_metrics() -> dict:
    """Collect all system metrics in one snapshot."""
    try:
        cpu_pct     = psutil.cpu_percent(interval=1)
        mem         = psutil.virtual_memory()
        gpu         = _get_gpu_metrics()
        ffmpeg      = _get_ffmpeg_stats()
        disk        = _get_disk_stats()
        buffer      = _get_buffer_stats()
        load_avg    = os.getloadavg()

        metrics = {
            "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cpu_pct":          round(cpu_pct, 1),
            "cpu_load_1m":      round(load_avg[0], 2),
            "cpu_load_5m":      round(load_avg[1], 2),
            "ram_used_pct":     mem.percent,
            "ram_used_gb":      round(mem.used  / (1024**3), 1),
            "ram_total_gb":     round(mem.total / (1024**3), 1),
            **gpu,
            **ffmpeg,
            **disk,
            **buffer,
        }
        return metrics
    except Exception as e:
        logger.error(f"collect_metrics failed: {e}", exc_info=True)
        return {}

# ─────────────────────────────────────────────────
# Format metrics for log line
# ─────────────────────────────────────────────────
def _format_metrics(m: dict) -> str:
    parts = []

    # CPU
    parts.append(f"CPU={m.get('cpu_pct','?')}% load={m.get('cpu_load_1m','?')}/{m.get('cpu_load_5m','?')}")

    # RAM
    parts.append(f"RAM={m.get('ram_used_gb','?')}GB/{m.get('ram_total_gb','?')}GB ({m.get('ram_used_pct','?')}%)")

    # GPU
    if m.get("gpu_util_pct", -1) >= 0:
        parts.append(
            f"GPU={m.get('gpu_util_pct','?')}% "
            f"GMEM={m.get('gpu_mem_used_mb','?')}/{m.get('gpu_mem_total_mb','?')}MB "
            f"GTEMP={m.get('gpu_temp_c','?')}°C"
        )
    else:
        parts.append("GPU=unavailable(NVML)")

    # FFmpeg
    cam1_cpu = m.get("ffmpeg_cam1_cpu_pct")
    cam2_cpu = m.get("ffmpeg_cam2_cpu_pct")
    if cam1_cpu is not None:
        parts.append(f"FFmpeg_cam1={cam1_cpu}%CPU")
    if cam2_cpu is not None:
        parts.append(f"FFmpeg_cam2={cam2_cpu}%CPU")

    # Disk
    parts.append(
        f"Disk={m.get('disk_free_gb','?')}GB free "
        f"({m.get('disk_used_pct','?')}% used)"
    )

    # MOG2 buffer
    parts.append(f"MOG2_buffer_pending={m.get('mog2_buffer_pending','?')} frames")

    return " | ".join(parts)

# ─────────────────────────────────────────────────
# Check if CPU is above threshold
# ─────────────────────────────────────────────────
def is_cpu_spike() -> tuple[bool, float]:
    """Returns (is_spike, current_cpu_pct). Fast check — 0.1s interval."""
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        return cpu >= CPU_THRESHOLD, cpu
    except Exception:
        return False, 0.0

def is_gpu_spike() -> tuple[bool, float]:
    """Returns (is_spike, current_gpu_mem_pct)."""
    try:
        gpu = _get_gpu_metrics()
        val = gpu.get("gpu_mem_util_pct", 0)
        if val < 0:
            return False, 0.0
        return val >= GPU_THRESHOLD, val
    except Exception:
        return False, 0.0

# ─────────────────────────────────────────────────
# Background metrics loop
# ─────────────────────────────────────────────────
_spike_active   = False
_on_spike_cb:    Optional[Callable] = None
_on_normal_cb:   Optional[Callable] = None
_on_disk_low_cb: Optional[Callable] = None

def set_spike_callbacks(on_spike: Callable, on_normal: Callable, on_disk_low: Optional[Callable] = None):
    """
    Register callbacks for CPU spike events.
    on_spike(cpu_pct)  → called when CPU goes above threshold
    on_normal(cpu_pct) → called when CPU returns below threshold
    """
    global _on_spike_cb, _on_normal_cb, _on_disk_low_cb
    _on_spike_cb    = on_spike
    _on_normal_cb   = on_normal
    _on_disk_low_cb = on_disk_low

async def _metrics_loop():
    global _spike_active
    logger.info(f"System metrics monitor started. "
                f"interval={METRICS_INTERVAL}s "
                f"cpu_threshold={CPU_THRESHOLD}% "
                f"gpu_threshold={GPU_THRESHOLD}%")

    while True:
        try:
            metrics = collect_metrics()
            if metrics:
                logger.info(_format_metrics(metrics))

                # CPU spike detection
                cpu = metrics.get("cpu_pct", 0)
                if cpu >= CPU_THRESHOLD and not _spike_active:
                    _spike_active = True
                    logger.warning(
                        f"CPU SPIKE DETECTED: {cpu}% >= threshold {CPU_THRESHOLD}% "
                        f"— YOLOX inference will pause"
                    )
                    if _on_spike_cb:
                        try:
                            _on_spike_cb(cpu)
                        except Exception as e:
                            logger.error(f"spike callback error: {e}", exc_info=True)

                elif cpu < CPU_THRESHOLD and _spike_active:
                    _spike_active = False
                    logger.info(
                        f"CPU normalized: {cpu}% < threshold {CPU_THRESHOLD}% "
                        f"— YOLOX inference resuming"
                    )
                    if _on_normal_cb:
                        try:
                            _on_normal_cb(cpu)
                        except Exception as e:
                            logger.error(f"normal callback error: {e}", exc_info=True)

                # Disk warning
                disk_free = metrics.get("disk_free_gb", 999)
                if isinstance(disk_free, (int, float)) and disk_free < 10:
                    logger.warning(
                        f"DISK LOW: only {disk_free}GB free — "
                        f"raw video and buffer may fail soon"
                    )
                    if _on_disk_low_cb:
                        try:
                            _on_disk_low_cb(disk_free)
                        except Exception as e:
                            logger.error(f"disk_low callback error: {e}")

                # GPU temp warning
                gpu_temp = metrics.get("gpu_temp_c", 0)
                if isinstance(gpu_temp, (int, float)) and 0 < gpu_temp > 80:
                    logger.warning(f"GPU TEMP HIGH: {gpu_temp}°C")

        except Exception as e:
            logger.error(f"metrics loop error: {e}", exc_info=True)

        await asyncio.sleep(METRICS_INTERVAL)

def start_metrics_monitor(on_spike: Optional[Callable] = None,
                           on_normal: Optional[Callable] = None,
                           on_disk_low: Optional[Callable] = None):
    """
    Start background metrics monitor.
    Call once at FastAPI startup.
    """
    if on_spike and on_normal:
        set_spike_callbacks(on_spike, on_normal)
    asyncio.create_task(_metrics_loop())
    logger.info("System metrics monitor task created")

