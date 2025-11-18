from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
from pathlib import Path
import traceback
import re

app = FastAPI(title="Camera URL Validator", version="2.0")

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


# ===================================================================
# ERROR PATTERN DETECTION
# ===================================================================

def detect_ffmpeg_error(output: str) -> str:
    """
    Analyze ffmpeg stderr and classify the issue.
    Returns a user-friendly message.
    """

    patterns = {

        # Authentication / wrong credentials
        r"401 Unauthorized": "Incorrect username or password.",
        r"403 Forbidden": "Access denied by camera (403).",
        r"authorization failed": "RTSP authorization failed.",

        # No stream found
        r"404 Not Found": "Stream path does not exist on camera.",
        r"Stream not found": "Camera stream not found.",
        r"Unknown error occurred": "Camera refused the stream.",

        # No video data / empty stream
        r"Could not find codec parameters": "Camera is online but not sending video data.",
        r"Invalid data found when processing input": "Camera returned invalid video data.",
        r"nonexisting PPS": "Camera stream is corrupted.",
        r"Missing reference picture": "Video stream has no usable frames.",

        # Network issues
        r"Connection refused": "Camera refused the connection.",
        r"Connection timed out": "Camera not responding on RTSP port.",
        r"Invalid argument": "Malformed RTSP URL or unsupported stream.",
        r"Network unreachable": "Network error reaching the camera.",
        r"Server returned 5\d\d": "Camera returned a server error.",

        # Freeze / no packets
        r"Input/output error": "Camera stopped sending packets.",
        r"failed to decode": "Camera is sending unreadable frames.",

        # Transport issues
        r"method DESCRIBE failed": "Camera did not accept RTSP DESCRIBE request.",
        r"method SETUP failed": "Camera refused SETUP. Wrong path or offline.",
    }

    for pattern, message in patterns.items():
        if re.search(pattern, output, re.IGNORECASE):
            return message

    return "Unknown RTSP error occurred."


# ===================================================================
# HELPERS
# ===================================================================

def ping_ip(ip: str) -> bool:
    """Ping the camera."""
    try:
        return subprocess.call(
            ["ping", "-c", "1", "-W", "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        ) == 0
    except Exception as e:
        print("[PING ERROR]", e)
        return False


def test_rtsp_ffmpeg(url: str) -> (bool, str):
    """
    Returns (success, message)
    message may contain ffmpeg diagnostics.
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

        # Debug log
        print("\n======= RAW FFMPEG OUTPUT =======")
        print(stderr_output)
        print("=================================\n")

        if proc.returncode == 0:
            return True, "Stream OK"

        # Process error patterns
        return False, detect_ffmpeg_error(stderr_output)

    except subprocess.TimeoutExpired:
        return False, "Camera timed out while reading video data."

    except FileNotFoundError:
        return False, "ffmpeg is not installed on the server."

    except Exception as e:
        print("[FFMPEG UNEXPECTED ERROR]", e)
        print(traceback.format_exc())
        return False, "Unexpected error while validating RTSP stream."


def save_rtsp(camera_angle: int, url: str):
    """Store RTSP URL in file."""
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
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to save RTSP URL to configuration file.")


# ===================================================================
# ROUTE
# ===================================================================

@app.post("/validate_and_update", response_model=ValidateResponse)
def validate_and_update(req: ValidateRequest):

    try:
        mode = req.mode.lower().strip()

        # ---------------- URL BUILDING ----------------
        if mode == "factory":
            auth = f"{req.userid}:{req.password}@" if req.userid or req.password else ""
            full_url = f"{req.protocol}://{auth}{req.ip}:{req.port}"

        elif mode == "office":
            full_url = f"{req.protocol}://{req.ip}:{req.port}/mystream"

        else:
            raise HTTPException(status_code=400, detail="Invalid mode: choose 'factory' or 'office'.")

        print(f"[VALIDATING] mode={mode}  url={full_url}")

        # ---------------- 1️⃣ PING CHECK ----------------
        if not ping_ip(req.ip):
            return ValidateResponse(ok=False, message="Camera unreachable (Ping failed).", url=None)

        # ---------------- 2️⃣ RTSP VALIDATION ----------------
        if req.protocol.lower() == "rtsp":
            success, msg = test_rtsp_ffmpeg(full_url)
            if not success:
                return ValidateResponse(ok=False, message=msg, url=None)

        # ---------------- 3️⃣ SAVE URL ----------------
        save_rtsp(req.camera_angle, full_url)

        return ValidateResponse(
            ok=True,
            message="Camera validated successfully.",
            url=full_url
        )

    except HTTPException:
        raise

    except Exception as e:
        print("[SERVER ERROR]", e)
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Unexpected server error: {str(e)}")