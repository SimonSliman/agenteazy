import re

PATTERNS = {
    "email": (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), 0.95),
    "phone": (re.compile(r'(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})'), 0.85),
    "ssn": (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), 0.95),
    "credit_card": (re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'), 0.90),
    "ip_address": (re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'), 0.80),
    "date_of_birth": (re.compile(r'\b(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(19|20)\d{2}\b'), 0.75),
    "us_passport": (re.compile(r'\b[A-Z]\d{8}\b'), 0.60),
    "iban": (re.compile(r'\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}\b'), 0.85),
}


def detect(text):
    try:
        findings = []
        for pii_type, (pattern, confidence) in PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append({
                    "type": pii_type,
                    "text": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                    "confidence": confidence,
                })
        findings.sort(key=lambda x: x["start"])
        types_found = list(set(f["type"] for f in findings))
        return {"findings": findings, "count": len(findings), "types_found": types_found}
    except Exception as e:
        return {"error": str(e)}
