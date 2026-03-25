from agenteazy_runtime import call_skill


def _safe_call(skill, data):
    try:
        return call_skill(skill, data)
    except Exception as e:
        return {"error": str(e)}


def analyze(url):
    """Analyze a competitor from their URL. Returns domain info, content analysis, keywords, and sentiment."""
    try:
        results = {"url": url}

        # 1. Extract domain info
        results["domain"] = _safe_call("domain-extract", {"url": url})

        # 2. Fetch and extract text (if HTML provided, use it; otherwise note limitation)
        # For now, caller passes html content directly
        # Future: add web fetch capability
        results["note"] = "Pass 'html' param with page content for full analysis"

        return results
    except Exception as e:
        return {"error": str(e)}


def analyze_page(url, html):
    """Full competitor analysis with HTML content provided."""
    try:
        results = {"url": url}

        # 1. Domain info
        results["domain"] = _safe_call("domain-extract", {"url": url})

        # 2. Extract text from HTML
        text_result = _safe_call("html-to-text", {"html": html})
        page_text = text_result.get("text", "") if isinstance(text_result, dict) else ""
        results["text_length"] = len(page_text)

        # 3. Keywords
        if page_text:
            results["keywords"] = _safe_call("keyword-extract", {"text": page_text, "top_n": 15})

        # 4. Sentiment
        if page_text:
            results["sentiment"] = _safe_call("sentiment-score", {"text": page_text[:5000]})

        # 5. Readability
        if page_text:
            results["readability"] = _safe_call("readability-score", {"text": page_text[:5000]})

        # 6. Summary
        if page_text and len(page_text) > 200:
            results["summary"] = _safe_call("text-summarize", {"text": page_text[:5000], "sentences": 3})

        # 7. Profanity check
        if page_text:
            results["profanity"] = _safe_call("profanity-check", {"text": page_text[:5000]})

        # Score: composite content quality
        readability = results.get("readability", {})
        flesch = readability.get("flesch_reading_ease", 50) if isinstance(readability, dict) else 50
        sentiment = results.get("sentiment", {})
        polarity = abs(sentiment.get("polarity", 0)) if isinstance(sentiment, dict) else 0

        content_score = min(100, max(0, int(flesch * 0.7 + polarity * 30 + len(page_text) / 100)))
        results["content_score"] = content_score

        return results
    except Exception as e:
        return {"error": str(e)}
