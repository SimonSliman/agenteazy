"""Test regex patterns against text and return match details."""

import re


def test(pattern: str, text: str) -> dict:
    """Test a regex pattern against text.

    Args:
        pattern: Regular expression pattern.
        text: Text to match against.

    Returns:
        Dict with matches, groups, and positions.
    """
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return {"error": f"Invalid regex: {e}", "matches": []}

    matches = []
    for m in compiled.finditer(text):
        matches.append({
            "match": m.group(),
            "start": m.start(),
            "end": m.end(),
            "groups": list(m.groups()) if m.groups() else [],
        })

    return {
        "pattern": pattern,
        "text": text,
        "match_count": len(matches),
        "matches": matches,
    }
