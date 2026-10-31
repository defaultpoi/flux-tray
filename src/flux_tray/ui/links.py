"""Validation helpers for links opened by the GTK interface."""

from urllib.parse import urlsplit


def is_valid_web_url(url: object) -> bool:
    """Return whether a value is a well-formed HTTP(S) URL suitable to open."""
    if not isinstance(url, str) or not url or any(ord(char) < 32 or char.isspace() for char in url):
        return False
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return False
        port = parsed.port
    except ValueError:
        return False
    return port is None or 1 <= port <= 65535
