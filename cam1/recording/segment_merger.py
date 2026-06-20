"""
cam1/recording/segment_merger.py — Segment Merger
===================================================
Merges raw segments into full video after session ends.
Uses FFmpeg concat (no re-encoding, fast).
Deletes segments after successful merge.
Max 80 lines. One responsibility: merge segments.
"""

import os
import subprocess
import threading
from typing import Optional, Callable

from core.config import getint, getbool
from core.logger import get_logger
from core.log_codes import get as LOG

logger  = get_logger("MERGE")
TIMEOUT = getint("MERGE_TIMEOUT_SECS",        1800)
DELETE  = getbool("DELETE_SEGMENTS_AFTER_MERGE", True)


def _write_concat(segments: list, path: str) -> bool:
    try:
        with open(path, "w") as f:
            for seg in segments:
                safe = seg.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        return True
    except Exception as e:
        logger.error(LOG("MERGE.003.ERROR", tx_id="?", error=e))
        return False


def _ffmpeg_concat(concat_path: str, output: str) -> bool:
    cmd = ["ffmpeg", "-f", "concat", "-safe", "0",
           "-i", concat_path, "-c", "copy", "-y", output]
    try:
        r = subprocess.run(cmd, capture_output=True,
                           text=True, timeout=TIMEOUT)
        if r.returncode == 0:
            size = os.path.getsize(output) / 1024 / 1024
            logger.info(LOG("MERGE.002.INFO",
                tx_id=os.path.basename(output)[:8],
                raw_ok=True, inf_ok=True))
            return True
        logger.error(LOG("MERGE.003.ERROR",
            tx_id="?", error=r.stderr[-200:]))
        return False
    except subprocess.TimeoutExpired:
        logger.error(LOG("MERGE.003.ERROR",
            tx_id="?", error=f"timeout {TIMEOUT}s"))
        return False
    except Exception as e:
        logger.error(LOG("MERGE.003.ERROR", tx_id="?", error=e))
        return False


def merge(
    transaction_id: str,
    date_dir: str,
    raw_segments: list,
    on_complete: Optional[Callable] = None,
) -> dict:
    result = {"raw_ok": False, "raw_full": None}
    raw_dir = os.path.join(date_dir, "raw")

    if not raw_segments:
        logger.warning(LOG("MERGE.005.WARN",
            type="raw", tx_id=transaction_id[:8]))
        return result

    logger.info(LOG("MERGE.001.INFO",
        tx_id=transaction_id[:8],
        raw_count=len(raw_segments), inf_count=0))

    concat = os.path.join(raw_dir, f"{transaction_id}_concat.txt")
    output = os.path.join(date_dir, f"{transaction_id}_raw_full.mp4")

    if _write_concat(raw_segments, concat):
        ok = _ffmpeg_concat(concat, output)
        result["raw_ok"]   = ok
        result["raw_full"] = output if ok else None
        try:
            os.remove(concat)
        except Exception:
            pass
        if ok and DELETE:
            deleted = 0
            for seg in raw_segments:
                try:
                    os.remove(seg)
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Could not delete {seg}: {e}")
            logger.info(LOG("MERGE.004.INFO", count=deleted))

    if on_complete:
        try:
            on_complete(result)
        except Exception:
            pass
    return result


def merge_background(
    transaction_id: str,
    date_dir: str,
    raw_segments: list,
    on_complete: Optional[Callable] = None,
) -> threading.Thread:
    t = threading.Thread(
        target=merge,
        args=(transaction_id, date_dir, raw_segments, on_complete),
        name=f"merge_{transaction_id[:8]}",
        daemon=True,
    )
    t.start()
    logger.info(LOG("MERGE.006.INFO", tx_id=transaction_id[:8]))
    return t
