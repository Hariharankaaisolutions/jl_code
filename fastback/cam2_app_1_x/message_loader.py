import os

class Messages:
    _messages = {}
    _loaded = False

    @classmethod
    def load(cls, path: str = "messages.properties"):
        if cls._loaded:
            return

        if not os.path.exists(path):
            raise FileNotFoundError(f"messages.properties not found at {path}")

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    cls._messages[key.strip()] = value.strip()

        cls._loaded = True

    @classmethod
    def get(cls, code: str, **kwargs) -> str:
        """
        Get a message by code.

        Example:
            Messages.get("DB.CONNECTION.001.ERROR", dbname="jlmill")
        """
        if not cls._loaded:
            cls.load()

        template = cls._messages.get(code, f"[MISSING MESSAGE: {code}]")
        try:
            if kwargs:
                return template.format(**kwargs)
            return template
        except Exception:
            # In case of bad placeholder, at least return something
            return template + f" [FORMAT ERROR kwargs={kwargs}]"
