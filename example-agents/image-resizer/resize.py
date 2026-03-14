"""Calculate image resize parameters and aspect ratios."""

import math


def resize(width: int, height: int, format: str = "png") -> dict:
    """Calculate resize parameters and aspect ratio for an image.

    Args:
        width: Target width in pixels.
        height: Target height in pixels.
        format: Output format (png, jpg, webp).

    Returns:
        Dict with dimensions, aspect ratio, and common preset fits.
    """
    if width <= 0 or height <= 0:
        return {"error": "Width and height must be positive integers"}

    gcd = math.gcd(width, height)
    aspect = f"{width // gcd}:{height // gcd}"

    presets = {
        "thumbnail": (150, int(150 * height / width)),
        "small": (320, int(320 * height / width)),
        "medium": (640, int(640 * height / width)),
        "large": (1280, int(1280 * height / width)),
        "hd": (1920, int(1920 * height / width)),
    }

    return {
        "original": {"width": width, "height": height},
        "aspect_ratio": aspect,
        "megapixels": round(width * height / 1_000_000, 2),
        "format": format.lower(),
        "presets": presets,
    }
