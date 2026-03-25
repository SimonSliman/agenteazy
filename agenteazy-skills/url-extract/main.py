import re
_URL_RE = re.compile(r'https?://[^\s<>"\')]+|www\.[^\s<>"\')]+\.[^\s<>"\')]+' )


def extract(text):
    try:
        urls = _URL_RE.findall(text)
        unique = list(set(urls))
        return {'urls': unique, 'count': len(unique)}
    except Exception as e:
        return {"error": str(e)}
