import scrubadub


def scrub(text):
    try:
        scrubber = scrubadub.Scrubber()
        filth = list(scrubber.iter_filth(text))
        detected = [
            {"type": f.type, "text": f.text, "start": f.beg, "end": f.end}
            for f in filth
        ]
        cleaned = scrubber.clean(text)
        return {"cleaned": cleaned, "detected": detected, "pii_count": len(detected)}
    except Exception as e:
        return {"error": str(e)}
