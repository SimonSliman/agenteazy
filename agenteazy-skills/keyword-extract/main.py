import yake


def extract(text, top_n=10):
    try:
        kw = yake.KeywordExtractor(n=3, top=int(top_n))
        keywords = kw.extract_keywords(text)
        return {
            "keywords": [{"keyword": k, "score": round(s, 4)} for k, s in keywords],
            "count": len(keywords),
        }
    except Exception as e:
        return {"error": str(e)}
