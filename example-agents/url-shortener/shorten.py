"""Generate short hash-based URL identifiers."""

import hashlib
import time


def shorten(url: str) -> str:
    """Generate a short hash identifier for a URL.

    Args:
        url: The full URL to shorten.

    Returns:
        A short alphanumeric identifier (8 chars).
    """
    if not url or not isinstance(url, str):
        return "error: invalid URL"

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    digest = hashlib.sha256(url.encode()).hexdigest()[:8]
    return f"https://aez.sh/{digest}"
