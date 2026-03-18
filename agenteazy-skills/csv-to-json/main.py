import csv
import io


def convert(csv_string: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(csv_string))
    return list(reader)
