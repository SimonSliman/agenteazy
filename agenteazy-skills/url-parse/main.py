from urllib.parse import urlparse


def parse(url: str) -> dict:
    try:
        parsed = urlparse(url)
        return {
            "scheme": parsed.scheme,
            "netloc": parsed.netloc,
            "path": parsed.path,
            "query": parsed.query,
            "fragment": parsed.fragment,
            "hostname": parsed.hostname,
            "port": parsed.port,
        }
    except Exception as e:
        return {"error": str(e)}
