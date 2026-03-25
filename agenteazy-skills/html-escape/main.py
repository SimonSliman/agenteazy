import html


def escape(text, unescape=False):
    try:
        if unescape:
            return {'result': html.unescape(text)}
        return {'result': html.escape(text)}
    except Exception as e:
        return {"error": str(e)}
