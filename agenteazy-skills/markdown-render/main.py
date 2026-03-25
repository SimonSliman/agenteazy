import markdown


def render(text):
    try:
        html = markdown.markdown(text, extensions=['tables', 'fenced_code'])
        return {'html': html, 'length': len(html)}
    except Exception as e:
        return {"error": str(e)}
