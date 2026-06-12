#!/bin/bash
# =============================================================
# jlcam_housekeeping.sh — JL-CAM Daily Cleanup Script
# Runs at 2AM via systemd timer
# =============================================================

LOG_FILE="/var/log/smartcounter/housekeeping.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    echo "[$DATE] $1" | tee -a "$LOG_FILE"
}

log "====== JL-CAM Housekeeping Started ======"

# =============================================================
# 1. CAM1 LOGS — zip after 2 days, delete after 14 days
# =============================================================
CAM1_LOGS="/opt/secure_ai/fastback/cam1_app_1_x/logs"

log "[CAM1] Zipping logs older than 2 days..."
find "$CAM1_LOGS" -type f -name "*.log" -mtime +2 | while read f; do
    gzip "$f" && log "[CAM1] Zipped: $f"
done

log "[CAM1] Deleting logs/zips older than 14 days..."
find "$CAM1_LOGS" -type f \( -name "*.log" -o -name "*.gz" -o -name "*.zip" \) -mtime +14 -delete
log "[CAM1] Done."

# =============================================================
# 2. CAM2 LOGS — zip after 2 days, delete after 14 days
# =============================================================
CAM2_LOGS="/opt/secure_ai/fastback/cam2_app_1/logs"

log "[CAM2] Zipping logs older than 2 days..."
find "$CAM2_LOGS" -type f -name "*.log" -mtime +2 | while read f; do
    gzip "$f" && log "[CAM2] Zipped: $f"
done

log "[CAM2] Deleting logs/zips older than 14 days..."
find "$CAM2_LOGS" -type f \( -name "*.log" -o -name "*.gz" -o -name "*.zip" \) -mtime +14 -delete
log "[CAM2] Done."

# =============================================================
# 3. HEARTBEAT LOG — truncate if larger than 10MB
# =============================================================
HEARTBEAT="/opt/secure_ai/heath_check/heartbeat.log"

if [ -f "$HEARTBEAT" ]; then
    SIZE=$(stat -c%s "$HEARTBEAT")
    if [ "$SIZE" -gt 10485760 ]; then
        truncate -s 0 "$HEARTBEAT"
        log "[HEARTBEAT] Truncated (was $(( SIZE / 1024 / 1024 ))MB)"
    else
        log "[HEARTBEAT] OK ($(( SIZE / 1024 ))KB — no action needed)"
    fi
fi

# =============================================================
# 4. DETECTION VIDEOS — delete older than 10 days
# =============================================================
CAM1_VIDEOS="/opt/secure_ai/fastback/cam1_app_1_x/detection_videos"
CAM2_VIDEOS="/opt/secure_ai/fastback/cam2_app_1/detection_videos"

for DIR in "$CAM1_VIDEOS" "$CAM2_VIDEOS"; do
    if [ -d "$DIR" ]; then
        COUNT=$(find "$DIR" -type f -mtime +10 | wc -l)
        find "$DIR" -type f -mtime +10 -delete
        log "[VIDEOS] Deleted $COUNT files older than 10 days from $DIR"
    fi
done

# =============================================================
# 5. DETECTED FRAMES — delete older than 30 days
# =============================================================
FRAMES_DIR="/opt/secure_ai/fastback/database/detected_frames"

if [ -d "$FRAMES_DIR" ]; then
    COUNT=$(find "$FRAMES_DIR" -type f -mtime +30 | wc -l)
    find "$FRAMES_DIR" -type f -mtime +30 -delete
    log "[FRAMES] Deleted $COUNT files older than 30 days"
fi

# =============================================================
# 6. REINFORCEMENT LEARNING DATA — delete older than 30 days
# =============================================================
RL_DIR="/opt/secure_ai/reinforcement_learning"

if [ -d "$RL_DIR" ]; then
    COUNT=$(find "$RL_DIR" -type f -mtime +30 | wc -l)
    find "$RL_DIR" -type f -mtime +30 -delete
    # Remove empty date folders
    find "$RL_DIR" -type d -empty -delete
    log "[RL] Deleted $COUNT files older than 30 days"
fi

# =============================================================
# 7. FFMPEG LOGS — delete older than 7 days
# =============================================================
FFMPEG_LOGS="/var/log/smartcounter"

COUNT=$(find "$FFMPEG_LOGS" -type f -name "ffmpeg*.log" -mtime +7 | wc -l)
find "$FFMPEG_LOGS" -type f -name "ffmpeg*.log" -mtime +7 -delete
log "[FFMPEG] Deleted $COUNT ffmpeg logs older than 7 days"

# =============================================================
# 8. JOURNALD — enforce 500MB cap
# =============================================================
journalctl --vacuum-size=500M >> "$LOG_FILE" 2>&1
log "[JOURNALD] Vacuum done"

# =============================================================
# DONE
# =============================================================
log "====== JL-CAM Housekeeping Complete ======"