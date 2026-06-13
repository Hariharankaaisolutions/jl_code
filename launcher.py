#!/usr/bin/env python3
# launcher.py — JL-CAM System Launcher with User Mode Switch
# ===========================================================
# MULTI_USER_MODE=false → only hp user allowed (developer/admin)
# MULTI_USER_MODE=true  → hp (admin) + smartclient (operator)
# ===========================================================

import os
import sys
import subprocess
import pwd

SCRIPT_TO_RUN = "/home/hp/script/smartclient_start.sh"
PROPS_FILE    = "/opt/secure_ai/fastback/cam1_app_1_x/app.properties"

def _load_multi_user_mode() -> bool:
    """Read MULTI_USER_MODE from app.properties."""
    try:
        with open(PROPS_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("MULTI_USER_MODE="):
                    val = line.split("=", 1)[1].strip().lower()
                    return val == "true"
    except Exception as e:
        print(f"[WARN] Could not read MULTI_USER_MODE from {PROPS_FILE}: {e}")
    return False  # default: single user (hp only)

def get_calling_username() -> str:
    return os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid()).pw_name

def main():
    calling_user    = get_calling_username()
    multi_user_mode = _load_multi_user_mode()

    # Determine allowed users based on mode
    if multi_user_mode:
        allowed_users = ["hp", "smartclient"]
        mode_label    = "MULTI_USER"
    else:
        allowed_users = ["hp", "smartclient"]  # smartclient runs the service
        mode_label    = "SINGLE_USER"

    print(f"[JL-CAM] Launcher starting → mode={mode_label} user={calling_user}")

    if calling_user not in allowed_users:
        print(
            f"[DENIED] User '{calling_user}' is not allowed. "
            f"Allowed: {allowed_users} (MULTI_USER_MODE={multi_user_mode})"
        )
        sys.exit(1)

    print(f"[JL-CAM] Starting JL-CAM AI System as user=hp script={SCRIPT_TO_RUN}")

    try:
        result = subprocess.run(
            ["sudo", "-u", "hp", "/bin/bash", SCRIPT_TO_RUN],
            check=False
        )
        sys.exit(result.returncode)
    except Exception as e:
        print(f"[ERROR] Launcher failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
