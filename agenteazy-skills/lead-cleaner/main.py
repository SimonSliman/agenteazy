import re
from agenteazy_runtime import call_skill

EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


def _safe_call(skill, data):
    try:
        return call_skill(skill, data)
    except Exception as e:
        return {"error": str(e)}


def clean(leads):
    """Clean a list of leads. Each lead = {"email": ..., "phone": ..., "notes": ...}"""
    try:
        if isinstance(leads, dict) and "rows" in leads:
            leads = leads["rows"]
        if not isinstance(leads, list):
            return {"error": "Expected a list of leads or {'rows': [...]}"}

        results = []
        for lead in leads:
            row = {"original": lead}

            email = lead.get("email", "")
            if email:
                row["email_valid"] = bool(EMAIL_RE.match(email.strip()))
                row["email_disposable"] = _safe_call("disposable-email-check", {"email": email})

            phone = lead.get("phone", "")
            if phone:
                row["phone_parsed"] = _safe_call("python-phonenumbers", {"phone": phone})

            text = lead.get("notes", "") or lead.get("name", "")
            if text:
                row["pii_scrubbed"] = _safe_call("pii-scrub", {"text": text})

            email_ok = row.get("email_valid", True)
            not_disposable = not row.get("email_disposable", {}).get("is_disposable", False)
            row["clean"] = email_ok and not_disposable

            results.append(row)

        clean_count = sum(1 for r in results if r["clean"])
        return {
            "total": len(results),
            "clean": clean_count,
            "flagged": len(results) - clean_count,
            "results": results,
        }
    except Exception as e:
        return {"error": str(e)}
