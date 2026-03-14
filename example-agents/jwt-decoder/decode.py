"""Decode JWT tokens without verification."""

import base64
import json


def _b64decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    return base64.urlsafe_b64decode(data + "=" * padding)


def decode(token: str) -> dict:
    """Decode a JWT token without signature verification.

    Args:
        token: Raw JWT string (header.payload.signature).

    Returns:
        Dict with header, payload, and signature info.
    """
    parts = token.strip().split(".")
    if len(parts) != 3:
        return {"error": f"Invalid JWT: expected 3 parts, got {len(parts)}"}

    try:
        header = json.loads(_b64decode(parts[0]))
    except Exception as e:
        return {"error": f"Failed to decode header: {e}"}

    try:
        payload = json.loads(_b64decode(parts[1]))
    except Exception as e:
        return {"error": f"Failed to decode payload: {e}"}

    return {
        "header": header,
        "payload": payload,
        "signature_present": bool(parts[2]),
        "algorithm": header.get("alg", "unknown"),
        "warning": "Signature NOT verified — do not trust for auth",
    }
