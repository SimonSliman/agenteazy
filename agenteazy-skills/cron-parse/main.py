from datetime import datetime
from croniter import croniter


def next_run(expression, count=5):
    try:
        cron = croniter(expression, datetime.now())
        runs = [cron.get_next(datetime).isoformat() for _ in range(int(count))]
        return {"expression": expression, "next_runs": runs, "count": len(runs)}
    except Exception as e:
        return {"error": str(e)}
