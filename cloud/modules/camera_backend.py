# modules/camera_backend.py

from fastapi import APIRouter

router = APIRouter(tags=["Camera Backend"])

# Camera backend functionality removed intentionally because
# this file accidentally contained OLD registration code which caused
# background tasks to crash using outdated send_mail() signature.
