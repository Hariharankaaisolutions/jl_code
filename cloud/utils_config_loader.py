# utils_config_loader.py

def load_properties(filepath: str) -> dict:
    """
    Very simple .properties loader: KEY=VALUE
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
        # Optional: you can log or print an error here if needed
        pass
    return data
