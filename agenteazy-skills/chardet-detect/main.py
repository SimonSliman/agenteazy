import chardet


def detect(text):
    try:
        result = chardet.detect(text.encode() if isinstance(text, str) else text)
        return result
    except Exception as e:
        return {"error": str(e)}
