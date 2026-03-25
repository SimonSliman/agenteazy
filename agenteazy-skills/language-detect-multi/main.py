from langdetect import detect, detect_langs


def detect_all(text):
    try:
        primary = detect(text)
        all_langs = detect_langs(text)
        return {'primary': primary, 'all': [{'lang': str(l.lang), 'prob': round(l.prob, 4)} for l in all_langs]}
    except Exception as e:
        return {"error": str(e)}
