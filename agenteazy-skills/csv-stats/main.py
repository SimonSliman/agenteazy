import csv
import io
import statistics


def analyze(csv_text):
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        if not rows:
            return {'error': 'No data rows found'}
        headers = list(rows[0].keys())
        return {'rows': len(rows), 'columns': len(headers), 'headers': headers}
    except Exception as e:
        return {"error": str(e)}
