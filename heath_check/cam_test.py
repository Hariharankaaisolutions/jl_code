from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
from pathlib import Path
import traceback
import re

app = FastAPI(title="Camera URL Validator", version="2.1")

RTSP_FILE = Path("/opt/vchanel/config/rtsp.properties")


# ===================================================================
# MODELS
# ===================================================================

class ValidateRequest(BaseModel):
    protocol: str
    ip: str
    userid: str
    password: str
    port: int
    camera_angle: int
    mode: str = "factory"


class ValidateResponse(BaseModel):
    ok: bool
    message: str
    url: str | None = None
    fps: float | None = None
    resolution: str | None = None
    codec: str | None = None


# ===================================================================
# ERROR PATTERN DETECTION
# ===================================================================

def detect_ffmpeg_error(output: str) -> str:
    patterns = {
        r"401 Unauthorized": "Incorrect username or password.",
        r"403 Forbidden": "Access denied by camera.",
        r"authorization failed": "RTSP authorization failed.",
        r"404 Not Found": "Stream path does not exist.",
        r"Stream not found": "Camera stream not found.",
        r"Unknown error occurred": "Camera refused the stream.",
        r"Could not find codec parameters": "Camera online but not sending video.",
        r"Invalid data found when processing input": "Camera returned invalid data.",
        r"nonexisting PPS": "Camera stream is corrupted.",
        r"Missing reference picture": "Video stream has no keyframes.",
        r"Connection refused": "Camera refused connection.",
        r"Connection timed out": "Camera not responding.",
        r"Invalid argument": "Malformed RTSP URL.",
        r"Network unreachable": "Network error reaching camera.",
        r"Server returned 5\d\d": "Camera returned server error.",
        r"Input/output error": "Camera stopped sending packets.",
        r"failed to decode": "Camera sending unreadable frames.",
        r"method DESCRIBE failed": "Camera did not accept DESCRIBE.",
        r"method SETUP failed": "Camera refused SETUP.",
    }

    for pattern, message in patterns.items():
        if re.search(pattern, output, re.IGNORECASE):
            return message

    return "Unknown RTSP error occurred."


# ===================================================================
# STREAM INFO PARSER
# ===================================================================

def parse_stream_info(stderr: str):
    """
    Extract codec, resolution, fps from FFmpeg stderr.
    """
    codec = None
    resolution = None
    fps = None

    pattern = r"Video:\s*([a-zA-Z0-9_]+).*?(\d{2,5}x\d{2,5}).*?(\d+(\.\d+)?)[ ]*fps"
    match = re.search(pattern, stderr, re.IGNORECASE)

    if match:
        codec = match.group(1)
        resolution = match.group(2)
        fps = float(match.group(3))

    return codec, resolution, fps


# ===================================================================
# HELPERS
# ===================================================================

def ping_ip(ip: str) -> bool:
    try:
        return subprocess.call(
            ["ping", "-c", "1", "-W", "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        ) == 0
    except:
        return False


def test_rtsp_ffmpeg(url: str):
    """
    Returns: (success, message, codec, resolution, fps)
    """

    cmd = [
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-frames:v", "1",
        "-f", "image2",
        "/tmp/rtsp_probe.jpg",
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )

        stderr_output = proc.stderr

        # Clean stderr log
        print("\n================= RAW FFMPEG OUTPUT =================")
        print(stderr_output)
        print("=====================================================\n")

        codec, resolution, fps = parse_stream_info(stderr_output)

        if proc.returncode == 0:
            return True, "Stream OK", codec, resolution, fps

        return False, detect_ffmpeg_error(stderr_output), codec, resolution, fps

    except subprocess.TimeoutExpired:
        return False, "Camera timed out while reading video.", None, None, None

    except FileNotFoundError:
        return False, "ffmpeg is not installed.", None, None, None

    except Exception as e:
        print("[FFMPEG ERROR]", e)
        print(traceback.format_exc())
        return False, "Unexpected FFmpeg error.", None, None, None


def save_rtsp(camera_angle: int, url: str):
    try:
        RTSP_FILE.parent.mkdir(parents=True, exist_ok=True)
        cam_map = {1: "", 2: ""}

        if RTSP_FILE.exists():
            for line in RTSP_FILE.read_text().splitlines():
                if "," in line:
                    angle, saved_url = line.split(",", 1)
                    try:
                        cam_map[int(angle)] = saved_url
                    except:
                        pass

        cam_map[camera_angle] = url

        with RTSP_FILE.open("w") as f:
            f.write(f"1,{cam_map[1]}\n")
            f.write(f"2,{cam_map[2]}\n")

    except Exception as e:
        print("[FILE WRITE ERROR]", e)
        raise HTTPException(status_code=500, detail="Failed to save RTSP URL.")


# ===================================================================
# ROUTE
# ===================================================================

@app.post("/validate_and_update", response_model=ValidateResponse)
def validate_and_update(req: ValidateRequest):

    try:
        mode = req.mode.lower()

        # ---------------- URL BUILD ----------------
        if mode == "factory":
            auth = f"{req.userid}:{req.password}@" if req.userid or req.password else ""
            full_url = f"{req.protocol}://{auth}{req.ip}:{req.port}"
        elif mode == "office":
            full_url = f"{req.protocol}://{req.ip}:{req.port}/mystream"
        else:
            raise HTTPException(status_code=400, detail="Invalid mode.")

        # Print URL header
        print("\n================= VALIDATION START =================")
        print(f"Generated URL: {full_url}")
        print("====================================================")

        # ---------------- PING ----------------
        if not ping_ip(req.ip):
            print("[PING FAILED] Camera unreachable.\n")
            return ValidateResponse(ok=False, message="Camera unreachable (Ping failed).")

        # ---------------- FFMPEG TEST ----------------
        codec, resolution, fps = None, None, None

        if req.protocol.lower() == "rtsp":
            success, msg, codec, resolution, fps = test_rtsp_ffmpeg(full_url)

            # Neat formatted log block
            print("\n================= CAMERA STREAM DETAILS =================")
            print(f"Generated URL   : {full_url}")
            print(f"Video Codec     : {codec if codec else 'N/A'}")
            print(f"Resolution      : {resolution if resolution else 'N/A'}")
            print(f"Frame Rate (FPS): {fps if fps else 'N/A'}")
            print("=========================================================\n")

            if not success:
                return ValidateResponse(
                    ok=False,
                    message=msg,
                    url=None,
                    codec=codec,
                    resolution=resolution,
                    fps=fps
                )

        # ---------------- SAVE URL ----------------
        save_rtsp(req.camera_angle, full_url)

        print("================= VALIDATION SUCCESS =================\n")

        return ValidateResponse(
            ok=True,
            message="Camera validated successfully.",
            url=full_url,
            codec=codec,
            resolution=resolution,
            fps=fps
        )

    except HTTPException:
        raise

    except Exception as e:
        print("[SERVER ERROR]", e)
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
