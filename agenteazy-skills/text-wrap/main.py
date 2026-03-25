import textwrap


def wrap(text, width=80):
    try:
        wrapped = textwrap.fill(text, width=int(width))
        return {'wrapped': wrapped, 'lines': len(wrapped.splitlines())}
    except Exception as e:
        return {"error": str(e)}
