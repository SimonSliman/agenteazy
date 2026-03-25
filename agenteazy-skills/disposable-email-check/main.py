import os

_blocklist = None

def _load_blocklist():
    global _blocklist
    if _blocklist is None:
        path = os.path.join(os.path.dirname(__file__), "blocklist.txt")
        with open(path) as f:
            _blocklist = set(line.strip().lower() for line in f if line.strip())
    return _blocklist

def check(email):
    try:
        if "@" not in email:
            return {"error": "Invalid email format - missing @"}
        blocklist = _load_blocklist()
        domain = email.strip().lower().split("@")[-1]
        return {"email": email, "domain": domain, "is_disposable": domain in blocklist, "blocklist_size": len(blocklist)}
    except Exception as e:
        return {"error": str(e)}
