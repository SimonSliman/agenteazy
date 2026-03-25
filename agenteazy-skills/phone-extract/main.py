import re
_PHONE_RE = re.compile(r'(\+?1[-.]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')


def extract(text):
    try:
        phones = _PHONE_RE.findall(text)
        raw_phones = [m.group() for m in _PHONE_RE.finditer(text)]
        return {'phones': raw_phones, 'count': len(raw_phones)}
    except Exception as e:
        return {"error": str(e)}
