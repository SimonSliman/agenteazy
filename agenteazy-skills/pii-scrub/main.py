import re

PATTERNS = {
    "email": re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
    "phone": re.compile(r'(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})'),
    "ssn": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    "credit_card": re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
}


def scrub(text):
    try:
        detected = []
        cleaned = text
        for pii_type, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                detected.append({"type": pii_type, "text": match.group(), "start": match.start(), "end": match.end()})
            cleaned = pattern.sub("{{" + pii_type.upper() + "}}", cleaned)
        return {"cleaned": cleaned, "detected": detected, "pii_count": len(detected)}
    except Exception as e:
        return {"error": str(e)}
