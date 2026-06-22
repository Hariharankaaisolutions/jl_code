#!/bin/bash
set -e

LOG_DIR="/opt/secure_ai/logs/$(date +%Y-%m-%d)"
VENV="/home/hp/Desktop/jlmill/bin/activate"

echo "Starting SmartClient Services..."

# Ensure log directory exists
mkdir -p $LOG_DIR

# ------------------------------
# 1. MediaMTX
# ------------------------------
echo "Starting MediaMTX..."
/bin/bash -c "source $VENV; cd /opt/mediamtx/; ./mediamtx >> $LOG_DIR/jlcam.log 2>&1" &
sleep 5

# ------------------------------
# 2. FFmpeg - CAM1
# ------------------------------
echo "Starting FFmpeg CAM1..."
/bin/bash -c "cd $LOG_DIR; ffmpeg -rtsp_transport tcp -c:v hevc_cuvid -i rtsp://admin:BOSS_321@172.30.30.231 -filter:v fps=15,scale=640:640 -c:v libx264 -preset ultrafast -tune zerolatency -b:v 1000k -maxrate 1000k -bufsize 2000k -c:a aac -ar 44100 -ac 2 -f flv rtmp://127.0.0.1/live/cam_1 >> $LOG_DIR/jlcam.log 2>&1" &
sleep 5

# ------------------------------
# 3. FFmpeg - CAM2
# ------------------------------
echo "Starting FFmpeg CAM2..."
/bin/bash -c "cd $LOG_DIR; ffmpeg -rtsp_transport tcp -c:v hevc_cuvid -i rtsp://admin:BOSS_321@172.30.30.230 -filter:v fps=15,scale=640:640 -c:v libx264 -preset ultrafast -tune zerolatency -b:v 1000k -maxrate 1000k -bufsize 2000k -c:a aac -ar 44100 -ac 2 -f flv rtmp://127.0.0.1/live/cam_2 >> $LOG_DIR/jlcam.log 2>&1" &
sleep 5

# ------------------------------
# 4. Registration API (9000)
# ------------------------------
echo "Starting Cloud API..."
/bin/bash -c "source $VENV; cd /opt/secure_ai/cloud; uvicorn main:app --host 0.0.0.0 --port 9000 >> $LOG_DIR/jlcam.log 2>&1" &
sleep 5

# ------------------------------
# 5. CAM1 API (8000)
# ------------------------------
echo "Starting CAM1 API..."
/bin/bash -c "source /opt/venv_y9/bin/activate; cd /opt/secure_ai; python3 -m uvicorn cam1.main:app --host 0.0.0.0 --port 8000 >> $LOG_DIR/jlcam.log 2>&1" &
sleep 5

# ------------------------------
# 6. CAM2 API (8001)
# ------------------------------
echo "Starting CAM2 API..."
/bin/bash -c "source $VENV; cd /opt/secure_ai/fastback/cam2_app_1; uvicorn main:app --host 0.0.0.0 --port 8001 >> $LOG_DIR/jlcam.log 2>&1" &
sleep 5

# ------------------------------
# 7. React App (3000)
# ------------------------------
echo "Starting React App..."
/bin/bash -c "cd /opt/secure_ai/myapp; BROWSER=none PORT=3000 npx react-scripts start >> $LOG_DIR/jlcam.log 2>&1" &
sleep 5

# ------------------------------
# 8. cam_test API (9010)
# ------------------------------
echo "Starting cam_test API..."
/bin/bash -c "source $VENV; cd /opt/secure_ai; uvicorn cam_test:app --host 0.0.0.0 --port 9010 >> $LOG_DIR/jlcam.log 2>&1" &
sleep 5

# ------------------------------
# 9. Health Monitor
# ------------------------------
echo "Starting Health Monitor..."
/bin/bash -c "source $VENV; cd /opt/secure_ai/heath_check; nohup python3 health_monitor.py > /dev/null 2>&1 & echo \$! > healthmonitor.pid"

echo "All SmartClient services started successfully."

sleep 10
DISPLAY=:0 XAUTHORITY=/home/smartclient/.Xauthority firefox http://localhost:3000 &

wait
