"""
metrics/alerter.py — Metrics Threshold Alerter
================================================
Checks metrics against thresholds from master.properties.
Sends alert emails when thresholds are exceeded.
Max 100 lines. One responsibility: check and alert.
"""

from core.config import getfloat, getint, getbool
from core.logger import get_logger
from core.log_codes import get as LOG
from core.mailer import send_metric_alert

logger = get_logger("METRICS")

# ── Thresholds ─────────────────────────────────────────────────
T_CPU_PCT   = getfloat("CPU_ALERT_THRESHOLD",  80)
T_CPU_TEMP  = getfloat("CPU_TEMP_THRESHOLD",   85)
T_RAM_PCT   = getfloat("RAM_ALERT_THRESHOLD",  90)
T_SWAP_PCT  = getfloat("SWAP_ALERT_THRESHOLD", 80)
T_GPU_UTIL  = getfloat("GPU_UTIL_THRESHOLD",   90)
T_GPU_MEM   = getfloat("GPU_MEM_THRESHOLD",    90)
T_GPU_TEMP  = getfloat("GPU_TEMP_THRESHOLD",   87)
T_GPU_FAN   = getfloat("GPU_FAN_THRESHOLD",    95)
T_GPU_PWR   = getfloat("GPU_POWER_THRESHOLD",  100)
T_DISK_FREE = getfloat("DISK_FREE_THRESHOLD_GB", 10)
T_DISK_PCT  = getfloat("DISK_USED_THRESHOLD",  90)
T_NET       = getfloat("NET_BANDWIDTH_THRESHOLD", 90)
T_PROC_CPU  = getfloat("PROCESS_CPU_THRESHOLD", 80)
T_MOG2      = getint("MOG2_BUFFER_THRESHOLD",   5)

# ── Alert switches ─────────────────────────────────────────────
A_CPU_PCT   = getbool("ALERT_CPU_HIGH",    True)
A_CPU_TEMP  = getbool("ALERT_CPU_TEMP",    True)
A_RAM       = getbool("ALERT_RAM_HIGH",    True)
A_SWAP      = getbool("ALERT_SWAP_HIGH",   True)
A_GPU_UTIL  = getbool("ALERT_GPU_UTIL",    True)
A_GPU_MEM   = getbool("ALERT_GPU_MEM",     True)
A_GPU_TEMP  = getbool("ALERT_GPU_TEMP",    True)
A_GPU_FAN   = getbool("ALERT_GPU_FAN",     True)
A_GPU_PWR   = getbool("ALERT_GPU_POWER",   True)
A_DISK_LOW  = getbool("ALERT_DISK_LOW",    True)
A_DISK_HIGH = getbool("ALERT_DISK_HIGH",   True)
A_NET       = getbool("ALERT_NET_HIGH",    True)
A_PROC      = getbool("ALERT_PROCESS_CPU", True)
A_MOG2      = getbool("ALERT_MOG2_BUFFER", True)


def _alert(enabled: bool, log_code: str, metric: str,
           value, threshold, unit: str = "%", **kw) -> None:
    if not enabled:
        return
    logger.warning(LOG(log_code, value=value, threshold=threshold, **kw))
    send_metric_alert(metric, value, threshold, unit)


def check(metrics: dict, mog2_pending: int = 0) -> None:
    """Check all metrics against thresholds. Send alerts if exceeded."""
    if not metrics:
        return

    cpu  = metrics.get("cpu_pct",    0)
    ctmp = metrics.get("cpu_temp",   0)
    ram  = metrics.get("ram_pct",    0)
    swap = metrics.get("swap_pct",   0)
    gu   = metrics.get("gpu_util",   0)
    gm   = metrics.get("gpu_mem_pct", 0)
    gt   = metrics.get("gpu_temp",   0)
    gf   = metrics.get("gpu_fan",    0)
    gp   = metrics.get("gpu_power",  0)
    df   = metrics.get("disk_free_gb", 999)
    dp   = metrics.get("disk_pct",   0)
    net  = metrics.get("net_mbps",   0)

    if cpu  > T_CPU_PCT:  _alert(A_CPU_PCT,  "MET.003.WARN", "CPU Usage",       cpu,  T_CPU_PCT)
    if ctmp > T_CPU_TEMP: _alert(A_CPU_TEMP, "MET.004.WARN", "CPU Temperature", ctmp, T_CPU_TEMP, "°C")
    if ram  > T_RAM_PCT:  _alert(A_RAM,      "MET.005.WARN", "RAM Usage",       ram,  T_RAM_PCT)
    if swap > T_SWAP_PCT: _alert(A_SWAP,     "MET.006.WARN", "Swap Usage",      swap, T_SWAP_PCT)
    if gu   > T_GPU_UTIL: _alert(A_GPU_UTIL, "MET.007.WARN", "GPU Utilization", gu,   T_GPU_UTIL)
    if gm   > T_GPU_MEM:  _alert(A_GPU_MEM,  "MET.008.WARN", "GPU Memory",      gm,   T_GPU_MEM)
    if gt   > T_GPU_TEMP: _alert(A_GPU_TEMP, "MET.009.WARN", "GPU Temperature", gt,   T_GPU_TEMP, "°C")
    if gf   > T_GPU_FAN:  _alert(A_GPU_FAN,  "MET.010.WARN", "GPU Fan Speed",   gf,   T_GPU_FAN)
    if gp   > T_GPU_PWR:  _alert(A_GPU_PWR,  "MET.011.WARN", "GPU Power",       gp,   T_GPU_PWR, "W")
    if df   < T_DISK_FREE:_alert(A_DISK_LOW, "MET.012.WARN", "Disk Free Space", df,   T_DISK_FREE, "GB")
    if dp   > T_DISK_PCT: _alert(A_DISK_HIGH,"MET.013.WARN", "Disk Usage",      dp,   T_DISK_PCT)
    if net  > T_NET:      _alert(A_NET,      "MET.014.WARN", "Network Bandwidth",net,  T_NET, "Mbps")
    if mog2_pending > T_MOG2:
        _alert(A_MOG2, "MET.016.WARN", "MOG2 Buffer", mog2_pending, T_MOG2, " frames")
