"""
core/log_codes.py — Log Code Loader
=====================================
Loads /opt/secure_ai/config/log_codes.properties
Provides LOG.get(code, **kwargs) for formatted log messages.
Max 50 lines. One responsibility: load and format log codes.
"""

from pathlib import Path

# ── Path ───────────────────────────────────────────────────────
CODES_PATH = Path("/opt/secure_ai/config/log_codes.properties")

# ── Internal store ─────────────────────────────────────────────
_codes: dict[str, str] = {}
_loaded: bool = False


def _load() -> None:
    global _codes, _loaded
    if _loaded:
        return
    if not CODES_PATH.exists():
        raise FileNotFoundError(f"Log codes not found: {CODES_PATH}")
    with open(CODES_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            _codes[k.strip()] = v.strip()
    _loaded = True


def get(code: str, **kwargs) -> str:
    """
    Get formatted log message for code.
    Example: LOG.get("DB.001.INFO", db="jlmill", host="localhost", port=5432)
    Returns: "[DB.001.INFO] DB pool created: jlmill@localhost:5432"
    """
    _load()
    template = _codes.get(code, f"[UNKNOWN CODE: {code}]")
    try:
        msg = template.format(**kwargs)
    except KeyError as e:
        msg = f"{template} [MISSING KEY: {e}]"
    return f"[{code}] {msg}"


def get_raw(code: str) -> str:
    """Get raw template without formatting."""
    _load()
    return _codes.get(code, f"[UNKNOWN CODE: {code}]")


def count() -> int:
    """Return total number of loaded codes."""
    _load()
    return len(_codes)


def all_codes() -> dict[str, str]:
    """Return all codes."""
    _load()
    return dict(_codes)
