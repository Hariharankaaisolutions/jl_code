# boot_report.py — Boot Report Email
# ====================================
# Sends a detailed system status email on every boot
# Contains:
#   - Boot time, kernel, uptime
#   - FFmpeg status (cam1/cam2)
#   - MediaMTX status
#   - Disk space
#   - GPU status
#   - Yesterday's total counts
#   - Today's auto-session schedule
# ====================================

import os
import smtplib
import subprocess
import psutil
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jl_logger import get_logger
from daily_counts_db import get_yesterday_totals
from system_metrics import collect_metrics

logger = get_logger("BOOTREPORT")

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

_props = _load_props()

ENABLED            = _props.get("BOOT_REPORT_ENABLED", "true").lower() == "true"
AUTO_START_DELAY   = int(_props.get("AUTO_START_DELAY_MINS", "10"))
AUTO_START_VEHICLE = _props.get("AUTO_START_VEHICLE", "XX00XX0000")
AUTO_STOP_TIME     = _props.get("AUTO_STOP_TIME", "18:00")

# Mail config
_MAIL_FILE = os.path.join(os.path.dirname(__file__), "config_mail.py")

def _load_mail_config():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("config_mail", _MAIL_FILE)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.EmailConfig
    except Exception as e:
        logger.error(f"Mail config load failed: {e}", exc_info=True)
        return None


# ─────────────────────────────────────────────────
# System info helpers
# ─────────────────────────────────────────────────
def _get_boot_time() -> str:
    try:
        bt = datetime.fromtimestamp(psutil.boot_time())
        return bt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "unknown"

def _get_kernel() -> str:
    try:
        return subprocess.check_output(["uname", "-r"], text=True).strip()
    except Exception:
        return "unknown"

def _get_uptime() -> str:
    try:
        bt      = psutil.boot_time()
        uptime  = datetime.now().timestamp() - bt
        hours   = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        return f"{hours}h {minutes}m"
    except Exception:
        return "unknown"

def _check_process(name_part: str) -> tuple[bool, str]:
    """Check if a process is running. Returns (running, pid_str)."""
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or [])
                if name_part in cmd or name_part in (proc.info.get("name") or ""):
                    return True, str(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False, "—"
    except Exception:
        return False, "—"

def _status_badge(ok: bool) -> str:
    return "✅ Running" if ok else "❌ Not Running"


# ─────────────────────────────────────────────────
# HTML builder
# ─────────────────────────────────────────────────
def _build_html(data: dict) -> str:
    yest  = data["yesterday"]
    metrics = data["metrics"]
    now_str = data["boot_time"]
    auto_start_time = data["auto_start_time"]

    def row(label, value, warn=False):
        color = "#E53935" if warn else "#1A237E"
        return f"""<tr>
            <td style="padding:8px 16px;color:#78909C;font-size:14px;width:45%;">{label}</td>
            <td style="padding:8px 16px;color:{color};font-size:14px;font-weight:600;">{value}</td>
        </tr>"""

    disk_free = metrics.get("disk_free_gb", "?")
    disk_warn = isinstance(disk_free, (int, float)) and disk_free < 20

    gpu_str = "unavailable (NVML mismatch)"
    if metrics.get("gpu_util_pct", -1) >= 0:
        gpu_str = (f"{metrics['gpu_util_pct']}% util | "
                   f"{metrics['gpu_mem_used_mb']}/{metrics['gpu_mem_total_mb']}MB | "
                   f"{metrics['gpu_temp_c']}°C")

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4f8;padding:40px 0;">
  <tr><td align="center">
  <table width="600" cellpadding="0" cellspacing="0"
         style="background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,0.08);overflow:hidden;">

    <!-- Header -->
    <tr><td style="background:linear-gradient(135deg,#1565C0,#0D47A1);padding:28px 40px;text-align:center;">
      <div style="font-size:32px;margin-bottom:6px;">🚀</div>
      <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">JL-CAM System Started</h1>
      <p style="margin:6px 0 0;color:#BBDEFB;font-size:13px;">
        {data['weekday']}, {data['date_str']} — Boot at {now_str}
      </p>
    </td></tr>

    <tr><td style="padding:32px 40px;">

      <!-- System Info -->
      <p style="margin:0 0 8px;font-size:11px;font-weight:700;color:#90A4AE;
                letter-spacing:1px;text-transform:uppercase;">System Info</p>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#F8FAFB;border-radius:12px;border:1px solid #E3EAF0;margin-bottom:24px;">
        {row("⏰ Boot Time", now_str)}
        {row("⏱ Uptime", data['uptime'])}
        {row("🐧 Kernel", data['kernel'])}
        {row("💾 RAM", f"{metrics.get('ram_used_gb','?')}GB / {metrics.get('ram_total_gb','?')}GB ({metrics.get('ram_used_pct','?')}%)")}
        {row("💿 Disk Free", f"{disk_free}GB free ({metrics.get('disk_used_pct','?')}% used)", warn=disk_warn)}
        {row("🎮 GPU", gpu_str)}
      </table>

      <!-- Services -->
      <p style="margin:0 0 8px;font-size:11px;font-weight:700;color:#90A4AE;
                letter-spacing:1px;text-transform:uppercase;">Services</p>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#F8FAFB;border-radius:12px;border:1px solid #E3EAF0;margin-bottom:24px;">
        {row("📡 MediaMTX", _status_badge(data['mediamtx_ok']))}
        {row("🎥 FFmpeg CAM1", _status_badge(data['ffmpeg_cam1_ok']))}
        {row("🎥 FFmpeg CAM2", _status_badge(data['ffmpeg_cam2_ok']))}
        {row("🔌 CAM1 API (8000)", _status_badge(data['cam1_api_ok']))}
        {row("☁️  Cloud API (9000)", _status_badge(data['cloud_api_ok']))}
        {row("🏥 Health Monitor", _status_badge(data['health_ok']))}
      </table>

      <!-- Yesterday Counts -->
      <p style="margin:0 0 8px;font-size:11px;font-weight:700;color:#90A4AE;
                letter-spacing:1px;text-transform:uppercase;">Yesterday's Counts ({yest['date']})</p>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#F8FAFB;border-radius:12px;border:1px solid #E3EAF0;margin-bottom:24px;">
        {row("📦 Box Count", yest['box'])}
        {row("🎁 Bale Count", yest['bale'])}
        {row("🛒 Trolley Count", yest['trolley'])}
        {row("🛍 Bag Count", yest['bag'])}
        {row("📊 Sessions", yest['session_count'])}
      </table>

      <!-- Today Schedule -->
      <div style="background:#E3F2FD;border-radius:10px;border-left:4px solid #1565C0;
                  padding:14px 18px;margin-bottom:24px;">
        <p style="margin:0;color:#0D47A1;font-size:14px;line-height:1.8;">
          🤖 <strong>Auto-session</strong> will start at <strong>{auto_start_time}</strong><br>
          🚗 Vehicle: <strong>{AUTO_START_VEHICLE}</strong><br>
          ⏹ Auto-stop at <strong>{AUTO_STOP_TIME}</strong><br>
          📹 Raw video saved until <strong>{AUTO_STOP_TIME}</strong>
        </p>
      </div>

    </td></tr>

    <!-- Footer -->
    <tr><td style="background:#F5F7FA;padding:18px 40px;border-top:1px solid #ECEFF1;text-align:center;">
      <p style="margin:0;color:#90A4AE;font-size:12px;">
        JL-CAM Harmony System — Automated Boot Report<br>
        Please do not reply to this email.
      </p>
    </td></tr>

  </table>
  </td></tr>
</table>
</body></html>"""


# ─────────────────────────────────────────────────
# Send boot report
# ─────────────────────────────────────────────────
def send_boot_report() -> bool:
    """
    Collect system state and send boot report email.
    Returns True on success.
    """
    if not ENABLED:
        logger.info("Boot report disabled (BOOT_REPORT_ENABLED=false)")
        return True

    logger.info("Preparing boot report email...")

    try:
        mail_cfg = _load_mail_config()
        if not mail_cfg:
            logger.error("Boot report skipped — mail config unavailable")
            return False

        # Collect data
        now             = datetime.now()
        metrics         = collect_metrics()
        yesterday       = get_yesterday_totals("cam_1")
        mediamtx_ok, _  = _check_process("mediamtx")
        ffmpeg_cam1_ok, _ = _check_process("cam_1")
        ffmpeg_cam2_ok, _ = _check_process("cam_2")
        cam1_api_ok, _  = _check_process("8000")
        cloud_api_ok, _ = _check_process("9000")
        health_ok, _    = _check_process("health_monitor")

        # Calculate auto-start time
        boot_h, boot_m      = now.hour, now.minute
        auto_start_minutes  = boot_m + AUTO_START_DELAY
        auto_start_h        = boot_h + auto_start_minutes // 60
        auto_start_m        = auto_start_minutes % 60
        auto_start_time     = f"{auto_start_h:02d}:{auto_start_m:02d}"

        data = {
            "boot_time":        now.strftime("%H:%M:%S"),
            "date_str":         now.strftime("%d %B %Y"),
            "weekday":          now.strftime("%A"),
            "uptime":           _get_uptime(),
            "kernel":           _get_kernel(),
            "metrics":          metrics,
            "yesterday":        yesterday,
            "mediamtx_ok":      mediamtx_ok,
            "ffmpeg_cam1_ok":   ffmpeg_cam1_ok,
            "ffmpeg_cam2_ok":   ffmpeg_cam2_ok,
            "cam1_api_ok":      cam1_api_ok,
            "cloud_api_ok":     cloud_api_ok,
            "health_ok":        health_ok,
            "auto_start_time":  auto_start_time,
        }

        # Build email
        subject = (
            f"🚀 JL-CAM System Started — {data['weekday']}, {data['date_str']} "
            f"| Auto-session at {auto_start_time}"
        )

        plain = (
            f"JL-CAM System Boot Report\n\n"
            f"Boot Time: {data['boot_time']}\n"
            f"Kernel: {data['kernel']}\n"
            f"Uptime: {data['uptime']}\n\n"
            f"Services:\n"
            f"  MediaMTX:     {'OK' if mediamtx_ok else 'NOT RUNNING'}\n"
            f"  FFmpeg CAM1:  {'OK' if ffmpeg_cam1_ok else 'NOT RUNNING'}\n"
            f"  CAM1 API:     {'OK' if cam1_api_ok else 'NOT RUNNING'}\n\n"
            f"Yesterday Counts ({yesterday['date']}):\n"
            f"  Box:     {yesterday['box']}\n"
            f"  Bale:    {yesterday['bale']}\n"
            f"  Trolley: {yesterday['trolley']}\n\n"
            f"Auto-session starts at {auto_start_time}\n"
            f"Auto-stop at {AUTO_STOP_TIME}\n"
        )

        msg = MIMEMultipart("alternative")
        msg["From"]    = mail_cfg.USERNAME
        msg["To"]      = ", ".join(mail_cfg.TO_EMAIL)
        msg["Subject"] = subject
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(_build_html(data), "html"))

        with smtplib.SMTP(mail_cfg.SMTP_SERVER, mail_cfg.SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(mail_cfg.USERNAME, mail_cfg.PASSWORD)
            server.send_message(msg)

        logger.info(f"Boot report sent → {mail_cfg.TO_EMAIL}")
        return True

    except Exception as e:
        logger.error(f"Boot report failed: {e}", exc_info=True)
        return False

