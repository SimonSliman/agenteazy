import difflib


def ratio(text1, text2):
    try:
        r = difflib.SequenceMatcher(None, text1, text2).ratio()
        return {'ratio': round(r, 4), 'percent': round(r * 100, 1)}
    except Exception as e:
        return {"error": str(e)}
