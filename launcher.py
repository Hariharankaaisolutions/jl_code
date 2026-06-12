#!/usr/bin/env python3
import os, sys, subprocess, pwd

ALLOWED_USER  = "smartclient"
SCRIPT_TO_RUN = "/home/hp/script/smartclient_start.sh"

def get_calling_username():
    return os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid()).pw_name

def main():
    calling_user = get_calling_username()

    if calling_user != ALLOWED_USER:
        print(f"[DENIED] Only '{ALLOWED_USER}' is allowed. Got: '{calling_user}'")
        sys.exit(1)

    print("Starting JL-CAM AI System...")

    try:
        result = subprocess.run(
            ["sudo", "-u", "hp", "/bin/bash", SCRIPT_TO_RUN],
            check=False
        )
        sys.exit(result.returncode)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
