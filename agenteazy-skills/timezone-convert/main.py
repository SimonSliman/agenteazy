from datetime import datetime
import pytz


def convert(dt_str, from_tz, to_tz):
    try:
        src = pytz.timezone(from_tz)
        dst = pytz.timezone(to_tz)
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = src.localize(dt)
        converted = dt.astimezone(dst)
        return {"original": dt_str, "from": from_tz, "to": to_tz, "converted": converted.isoformat()}
    except Exception as e:
        return {"error": str(e)}
