#!/bin/bash

LOG_DIR="/var/log/smartcounter"
VENV="/home/hp/Desktop/jlmill/bin/activate"

mkdir -p $LOG_DIR

# ------------------------------
# 1. MediaMTX
# ------------------------------
/bin/bash -c "source $VENV; cd /opt/mediamtx/; ./mediamtx 2>&1 | tee $LOG_DIR/mediamtx_log.txt" &
sleep 5

# ------------------------------
# 2. FFmpeg - CAM1
# ------------------------------
sudo -u hp /bin/bash -c "cd $LOG_DIR; ffmpeg -rtsp_transport tcp -c:v hevc_cuvid -i rtsp://admin:BOSS_321@172.30.30.231 -filter:v fps=15,scale=640:640 -c:v libx264 -preset ultrafast -tune zerolatency -b:v 1000k -maxrate 1000k -bufsize 2000k -c:a aac -ar 44100 -ac 2 -f flv rtmp://127.0.0.1/live/cam_1 > $LOG_DIR/ffmpeg_cam1_log.txt 2>&1" &
sleep 5

# ------------------------------
# 3. FFmpeg - CAM2
# ------------------------------
sudo -u hp /bin/bash -c "cd $LOG_DIR; ffmpeg -rtsp_transport tcp -c:v hevc_cuvid -i rtsp://admin:BOSS_321@172.30.30.230 -filter:v fps=15,scale=640:640 -c:v libx264 -preset ultrafast -tune zerolatency -b:v 1000k -maxrate 1000k -bufsize 2000k -c:a aac -ar 44100 -ac 2 -f flv rtmp://127.0.0.1/live/cam_2 > $LOG_DIR/ffmpeg_cam2_log.txt 2>&1" &
sleep 5

# ------------------------------
# 4. Registration API (9000)
# ------------------------------
/bin/bash -c "source $VENV; cd /opt/secure_ai/cloud; uvicorn main:app --host 0.0.0.0 --port 9000 --reload > $LOG_DIR/cloud_api_log.txt 2>&1" &
sleep 5

# ------------------------------
# 5. CAM1 API (8000)
# ------------------------------
/bin/bash -c "source /opt/venv_y9/bin/activate; cd /opt/secure_ai/fastback/cam1_app_1_x; uvicorn main:app --host 0.0.0.0 --port 8000 > $LOG_DIR/cam1_api_log.txt 2>&1" &
sleep 5

# ------------------------------
# 6. CAM2 API (8001)
# ------------------------------
/bin/bash -c "source $VENV; cd /opt/secure_ai/fastback/cam2_app_1; uvicorn main:app --host 0.0.0.0 --port 8001 --reload > $LOG_DIR/cam2_api_log.txt 2>&1" &
sleep 5

# ------------------------------
# 7. React App (3000)
# ------------------------------
/bin/bash -c "cd /opt/secure_ai/myapp; BROWSER=none PORT=3000 npx react-scripts start > $LOG_DIR/react_app_log.txt 2>&1" &
sleep 5

# ------------------------------
# 8. cam_test API (9010)
# ------------------------------
/bin/bash -c "source $VENV; cd /opt/secure_ai; uvicorn cam_test:app --host 0.0.0.0 --port 9010 --reload > $LOG_DIR/cam_test_api_log.txt 2>&1" &
sleep 5

# ------------------------------
# 9. Health Monitor
# ------------------------------
/bin/bash -c "source $VENV; cd /opt/secure_ai/heath_check; nohup python3 health_monitor.py > /dev/null 2>&1 & echo \$! > healthmonitor.pid"

sleep 10
firefox http://localhost:3000 &
wait
