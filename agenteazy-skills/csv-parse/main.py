import csv
import io


def parse(csv_text, has_header=True):
    try:
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        if not rows:
            return {"error": "No data found"}

        if has_header and len(rows) > 1:
            headers = rows[0]
            data = [dict(zip(headers, row)) for row in rows[1:]]
            return {"headers": headers, "rows": data, "row_count": len(data), "column_count": len(headers)}
        else:
            return {"rows": rows, "row_count": len(rows), "column_count": len(rows[0]) if rows else 0}
    except Exception as e:
        return {"error": str(e)}
