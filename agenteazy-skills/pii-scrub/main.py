import scrubadub


def scrub(text):
    scrubber = scrubadub.Scrubber()
    filth = list(scrubber.iter_filth(text))
    cleaned = scrubber.clean(text)
    detected = [{"type": f.type, "text": f.text, "start": f.beg, "end": f.end} for f in filth]
    return {"cleaned": cleaned, "detected": detected, "pii_count": len(detected)}
