"""Analyze CSV data and return summary statistics."""

import csv
import io


def analyze(csv_data: str) -> dict:
    """Analyze a CSV string and return structure and basic statistics.

    Args:
        csv_data: Raw CSV content as a string.

    Returns:
        Dict with rows, columns, column_names, sample_data, and basic_stats.
    """
    try:
        reader = csv.DictReader(io.StringIO(csv_data))
        rows = list(reader)
        if not rows:
            return {"rows": 0, "columns": 0, "column_names": [], "error": "Empty CSV"}

        columns = list(rows[0].keys())
        stats = {}
        for col in columns:
            values = [r[col] for r in rows if r[col]]
            numeric = []
            for v in values:
                try:
                    numeric.append(float(v))
                except ValueError:
                    pass
            if numeric:
                stats[col] = {
                    "min": min(numeric), "max": max(numeric),
                    "mean": round(sum(numeric) / len(numeric), 2),
                    "count": len(numeric),
                }
            else:
                stats[col] = {"unique": len(set(values)), "count": len(values)}

        return {
            "rows": len(rows), "columns": len(columns),
            "column_names": columns, "sample_data": rows[:3],
            "basic_stats": stats,
        }
    except Exception as e:
        return {"error": str(e)}
