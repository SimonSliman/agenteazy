from urllib.parse import quote, unquote


def encode(text, decode=False):
    try:
        if decode:
            return {'result': unquote(text)}
        return {'result': quote(text)}
    except Exception as e:
        return {"error": str(e)}
