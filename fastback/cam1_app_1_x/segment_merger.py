# segment_merger.py — Segment Merger
# ====================================
# After session ends and all inference is complete:
# 1. Merges raw segments → tx_raw_full.mp4
# 2. Merges inferred segments → tx_inferred_full.mp4
# 3. Deletes individual segments
# Uses FFmpeg concat (no re-encoding, fast)
# ====================================

import os
import subprocess
import time
import threading
from typing import Optional
from jl_logger import get_logger

logger = get_logger("SEG_MERGE")

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

_props                   = _load_props()
MERGE_TIMEOUT_SECS       = int(_props.get("MERGE_TIMEOUT_SECS",            "1800"))
DELETE_AFTER_MERGE       = _props.get("DELETE_SEGMENTS_AFTER_MERGE", "true").lower() == "true"


def _build_concat_file(segments: list, concat_path: str) -> bool:
    """Write FFmpeg concat list file."""
    try:
        with open(concat_path, "w") as f:
            for seg in segments:
                # Escape single quotes in path
                safe = seg.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        return True
    except Exception as e:
        logger.error(f"Failed to write concat file: {e}")
        return False


def _ffmpeg_concat(concat_path: str, output_path: str) -> bool:
    """Run FFmpeg concat demuxer. Returns True on success."""
    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_path,
        "-c", "copy",
        "-y",
        output_path
    ]
    logger.info(f"FFmpeg merge → output={os.path.basename(output_path)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=MERGE_TIMEOUT_SECS
        )
        if result.returncode == 0:
            size_mb = os.path.getsize(output_path) / 1024 / 1024
            logger.info(
                f"Merge complete → "
                f"{os.path.basename(output_path)} "
                f"size={size_mb:.1f}MB"
            )
            return True
        else:
            logger.error(
                f"FFmpeg merge failed rc={result.returncode} "
                f"err={result.stderr[-300:]}"
            )
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg merge timed out after {MERGE_TIMEOUT_SECS}s")
        return False
    except Exception as e:
        logger.error(f"FFmpeg merge exception: {e}", exc_info=True)
        return False


def merge_segments(
    transaction_id:   str,
    date_dir:         str,
    raw_segments:     list,
    inferred_segments: list,
) -> dict:
    """
    Merge raw and inferred segments into full videos.
    Returns dict with paths of merged files.
    """
    result = {
        "raw_full":      None,
        "inferred_full": None,
        "raw_ok":        False,
        "inferred_ok":   False,
    }

    raw_dir      = os.path.join(date_dir, "raw")
    inferred_dir = os.path.join(date_dir, "inferred")

    # ── Merge raw segments ──────────────────────────────────────
    if raw_segments:
        logger.info(
            f"Merging {len(raw_segments)} raw segments → "
            f"tx={transaction_id[:8]}"
        )
        raw_concat  = os.path.join(raw_dir, f"{transaction_id}_raw_concat.txt")
        raw_output  = os.path.join(date_dir, f"{transaction_id}_raw_full.mp4")

        if _build_concat_file(raw_segments, raw_concat):
            ok = _ffmpeg_concat(raw_concat, raw_output)
            result["raw_ok"]   = ok
            result["raw_full"] = raw_output if ok else None

            # Cleanup concat file
            try:
                os.remove(raw_concat)
            except Exception:
                pass

            # Delete raw segments after successful merge
            if ok and DELETE_AFTER_MERGE:
                deleted = 0
                for seg in raw_segments:
                    try:
                        os.remove(seg)
                        deleted += 1
                    except Exception as e:
                        logger.warning(f"Could not delete raw segment {seg}: {e}")
                logger.info(
                    f"Deleted {deleted}/{len(raw_segments)} raw segments "
                    f"tx={transaction_id[:8]}"
                )
    else:
        logger.warning(f"No raw segments to merge → tx={transaction_id[:8]}")

    # ── Merge inferred segments ─────────────────────────────────
    if inferred_segments:
        logger.info(
            f"Merging {len(inferred_segments)} inferred segments → "
            f"tx={transaction_id[:8]}"
        )
        inf_concat = os.path.join(
            inferred_dir, f"{transaction_id}_inf_concat.txt"
        )
        inf_output = os.path.join(
            date_dir, f"{transaction_id}_inferred_full.mp4"
        )

        if _build_concat_file(inferred_segments, inf_concat):
            ok = _ffmpeg_concat(inf_concat, inf_output)
            result["inferred_ok"]   = ok
            result["inferred_full"] = inf_output if ok else None

            # Cleanup concat file
            try:
                os.remove(inf_concat)
            except Exception:
                pass

            # Delete inferred segments after successful merge
            if ok and DELETE_AFTER_MERGE:
                deleted = 0
                for seg in inferred_segments:
                    try:
                        os.remove(seg)
                        deleted += 1
                    except Exception as e:
                        logger.warning(
                            f"Could not delete inferred segment {seg}: {e}"
                        )
                logger.info(
                    f"Deleted {deleted}/{len(inferred_segments)} "
                    f"inferred segments tx={transaction_id[:8]}"
                )
    else:
        logger.warning(
            f"No inferred segments to merge → tx={transaction_id[:8]}"
        )

    logger.info(
        f"Merge complete → tx={transaction_id[:8]} "
        f"raw_ok={result['raw_ok']} "
        f"inferred_ok={result['inferred_ok']} "
        f"raw={os.path.basename(result['raw_full'] or 'none')} "
        f"inferred={os.path.basename(result['inferred_full'] or 'none')}"
    )
    return result


def merge_in_background(
    transaction_id:    str,
    date_dir:          str,
    raw_segments:      list,
    inferred_segments: list,
    on_complete:       Optional[callable] = None,
):
    """Run merge in background thread. Calls on_complete(result) when done."""
    def _run():
        result = merge_segments(
            transaction_id=transaction_id,
            date_dir=date_dir,
            raw_segments=raw_segments,
            inferred_segments=inferred_segments,
        )
        if on_complete:
            try:
                on_complete(result)
            except Exception as e:
                logger.error(f"merge on_complete callback error: {e}")

    t = threading.Thread(
        target=_run,
        name=f"seg_merge_{transaction_id[:8]}",
        daemon=True
    )
    t.start()
    logger.info(f"Merge started in background → tx={transaction_id[:8]}")
    return t
