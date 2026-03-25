import textdistance


def compare(text1, text2, method="levenshtein"):
    try:
        fn = getattr(textdistance, method, textdistance.levenshtein)
        dist = fn.distance(text1, text2)
        sim = fn.normalized_similarity(text1, text2)
        return {'distance': dist, 'similarity': round(sim, 4), 'method': method}
    except Exception as e:
        return {"error": str(e)}
