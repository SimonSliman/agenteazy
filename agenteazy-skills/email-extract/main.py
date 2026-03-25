import re
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')


def extract(text):
    try:
        emails = _EMAIL_RE.findall(text)
        unique = list(set(emails))
        return {'emails': unique, 'count': len(unique)}
    except Exception as e:
        return {"error": str(e)}
