from agenteazy_runtime import call_skill


def _safe_call(skill, data):
    try:
        return call_skill(skill, data)
    except Exception as e:
        return {"error": str(e)}


def repurpose(html, source_url=""):
    """Take HTML content and repurpose it: extract text, summarize, extract keywords, analyze sentiment, score readability."""
    try:
        results = {"source_url": source_url}

        # 1. Extract text from HTML
        text_result = _safe_call("html-to-text", {"html": html})
        page_text = text_result.get("text", "") if isinstance(text_result, dict) else ""
        results["extracted_text"] = page_text[:2000]
        results["full_length"] = len(page_text)

        if not page_text:
            return {"error": "No text extracted from HTML"}

        # 2. Summarize
        if len(page_text) > 200:
            results["summary"] = _safe_call("text-summarize", {"text": page_text[:5000], "sentences": 3})

        # 3. Keywords for tagging/SEO
        results["keywords"] = _safe_call("keyword-extract", {"text": page_text, "top_n": 10})

        # 4. Sentiment (tone of original)
        results["sentiment"] = _safe_call("sentiment-score", {"text": page_text[:5000]})

        # 5. Readability
        results["readability"] = _safe_call("readability-score", {"text": page_text[:5000]})

        # 6. Generate slug from top keyword
        keywords = results.get("keywords", {})
        if isinstance(keywords, dict) and keywords.get("keywords"):
            top_kw = keywords["keywords"][0]["keyword"]
            results["suggested_slug"] = _safe_call("python-slugify", {"text": top_kw})

        # 7. Profanity check before repurposing
        results["profanity"] = _safe_call("profanity-check", {"text": page_text[:5000]})

        return results
    except Exception as e:
        return {"error": str(e)}
