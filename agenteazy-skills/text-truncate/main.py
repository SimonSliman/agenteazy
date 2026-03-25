


def truncate(text, max_length=280, suffix="..."):
    try:
        ml = int(max_length)
        if len(text) <= ml:
            return {'text': text, 'truncated': False}
        return {'text': text[:ml - len(suffix)] + suffix, 'truncated': True, 'original_length': len(text)}
    except Exception as e:
        return {"error": str(e)}
