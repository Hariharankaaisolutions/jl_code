# utils_config_loader.py

def load_properties(filepath: str) -> dict:
    """
    Simple .properties loader: KEY=VALUE
    Ignores empty lines and lines starting with '#'
    """
    data: dict[str, str] = {}
    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    data[key.strip()] = value.strip()
    except FileNotFoundError:
        pass

    # ── Resolve IMAGE_BASE_URL from IMAGE_MODE ──────────────────
    # IMAGE_MODE = lan | tailscale | localhost
    # Whichever is set, IMAGE_BASE_URL is automatically resolved
    # so the rest of the codebase just reads IMAGE_BASE_URL as before.
    mode = data.get("IMAGE_MODE", "lan").strip().lower()

    mode_map = {
        "lan":       data.get("IMAGE_BASE_URL_LAN",       "http://172.30.30.169:9000/images"),
        "tailscale": data.get("IMAGE_BASE_URL_TAILSCALE", "http://100.96.123.113:9000/images"),
        "localhost": data.get("IMAGE_BASE_URL_LOCALHOST", "http://localhost:9000/images"),
    }

    data["IMAGE_BASE_URL"] = mode_map.get(mode, mode_map["tailscale"])

    return data