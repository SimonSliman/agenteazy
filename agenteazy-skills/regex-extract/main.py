import re


def extract(text, pattern):
    try:
        matches = re.findall(pattern, text)
        return {'matches': matches, 'count': len(matches), 'pattern': pattern}
    except Exception as e:
        return {"error": str(e)}
