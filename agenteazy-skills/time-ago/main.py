import humanize
from datetime import datetime


def format(iso_date):
    try:
        dt = datetime.fromisoformat(iso_date)
        return {'ago': humanize.naturaltime(dt), 'date': humanize.naturaldate(dt), 'original': iso_date}
    except Exception as e:
        return {"error": str(e)}
