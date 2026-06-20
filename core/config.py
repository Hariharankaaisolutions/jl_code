"""
core/config.py — Master Config Loader
======================================
Reads /opt/secure_ai/config/master.properties
Single source of truth for all system settings.
Max 50 lines. One responsibility: load and expose config.
"""

import os
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────
BASE_DIR    = Path("/opt/secure_ai")
CONFIG_PATH = BASE_DIR / "config" / "master.properties"

# ── Internal store ─────────────────────────────────────────────
_cfg: dict[str, str] = {}
_loaded: bool = False


def _load() -> None:
    global _cfg, _loaded
    if _loaded:
        return
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Master config not found: {CONFIG_PATH}")
    with open(CONFIG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            _cfg[k.strip()] = v.strip()
    _loaded = True


def get(key: str, default: Any = None) -> str:
    _load()
    val = os.getenv(key, _cfg.get(key, default))
    return str(val) if val is not None else default


def getint(key: str, default: int = 0) -> int:
    try:
        return int(get(key, default))
    except (TypeError, ValueError):
        return int(default)


def getfloat(key: str, default: float = 0.0) -> float:
    try:
        return float(get(key, default))
    except (TypeError, ValueError):
        return float(default)


def getbool(key: str, default: bool = False) -> bool:
    val = get(key, None)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def getlist(key: str, sep: str = ",") -> list[str]:
    val = get(key, None)
    if not val:
        return []
    return [x.strip() for x in val.split(sep) if x.strip()]


def getmap(key: str, item_sep: str = ",", kv_sep: str = ":") -> dict[str, int]:
    val = get(key, None)
    if not val:
        return {}
    out = {}
    for item in val.split(item_sep):
        if kv_sep in item:
            k, v = item.split(kv_sep, 1)
            try:
                out[k.strip()] = int(v.strip())
            except ValueError:
                out[k.strip()] = v.strip()
    return out


def all_keys() -> dict[str, str]:
    _load()
    return dict(_cfg)
