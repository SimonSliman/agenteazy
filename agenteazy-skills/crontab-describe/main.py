from croniter import croniter
from datetime import datetime


def describe(expression):
    try:
        parts = expression.split()
        labels = ['minute', 'hour', 'day_of_month', 'month', 'day_of_week']
        parsed = dict(zip(labels, parts)) if len(parts) == 5 else {}
        cron = croniter(expression, datetime.now())
        next_5 = [cron.get_next(datetime).isoformat() for _ in range(5)]
        return {'expression': expression, 'parsed': parsed, 'next_5_runs': next_5}
    except Exception as e:
        return {"error": str(e)}
