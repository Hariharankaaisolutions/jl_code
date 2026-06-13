import os
import subprocess
from datetime import datetime
from config_loader import VIDEO_SAVE_DIR
from smart_logger import get_logger

logger = get_logger(__name__)

# Store FFmpeg process per transaction_id
recorders = {}


def start_raw_recording(transaction_id: str, rtmp_url: str):
    """
    Start FFmpeg raw RTMP recording.
    Saves file under:
    VIDEO_SAVE_DIR_raw/raw_video/<YYYY-MM-DD>/<transaction_id>.mp4
    """

    # Generate date folder (YYYY-MM-DD)
    date_folder = datetime.now().strftime("%Y-%m-%d")

    # Build directory path
    save_dir = os.path.join(VIDEO_SAVE_DIR, "raw_video", date_folder)
    os.makedirs(save_dir, exist_ok=True)

    # Output file path
    output_file = os.path.join(save_dir, f"{transaction_id}.ts")

    logger.info(f"🎥 Starting RAW RTMP recording → {output_file}")

    # FFmpeg copy-stream recording
    cmd = [
        "ffmpeg",
        "-i", rtmp_url,
        "-c", "copy",
        "-f", "mpegts",
        output_file
    ]

    # Start FFmpeg background process
    proc = subprocess.Popen(cmd)
    recorders[transaction_id] = proc

    return output_file


def stop_raw_recording(transaction_id: str):
    """
    Stop recording for given transaction_id.
    """
    proc = recorders.get(transaction_id)

    if not proc:
        logger.warning(f"No active raw recorder found for transaction_id={transaction_id}")
        return

    try:
        proc.terminate()
        proc.wait(timeout=5)
        logger.info(f"🛑 Stopped RAW recording for transaction_id={transaction_id}")
    except Exception as e:
        logger.exception(f"Failed to stop RAW RTMP recording: {e}")

    recorders.pop(transaction_id, None)
