"""Parse cron expressions into human-readable descriptions."""

_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _describe_field(value: str, name: str) -> str:
    if value == "*":
        return f"every {name}"
    if "/" in value:
        base, step = value.split("/", 1)
        return f"every {step} {name}s"
    if "," in value:
        return f"{name} {value}"
    if "-" in value:
        lo, hi = value.split("-", 1)
        return f"{name} {lo} through {hi}"
    return f"{name} {value}"


def parse(expression: str) -> dict:
    """Parse a cron expression into a human-readable description.

    Args:
        expression: Standard 5-field cron expression (min hour dom month dow).

    Returns:
        Dict with fields breakdown and human-readable description.
    """
    parts = expression.strip().split()
    if len(parts) != 5:
        return {"error": f"Expected 5 fields, got {len(parts)}", "expression": expression}

    minute, hour, dom, month, dow = parts
    fields = {
        "minute": minute, "hour": hour,
        "day_of_month": dom, "month": month, "day_of_week": dow,
    }

    descriptions = [
        _describe_field(minute, "minute"),
        _describe_field(hour, "hour"),
        _describe_field(dom, "day"),
        _describe_field(month, "month"),
        _describe_field(dow, "weekday"),
    ]

    return {
        "expression": expression,
        "fields": fields,
        "description": ", ".join(descriptions),
    }
