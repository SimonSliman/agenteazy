from agenteazy_runtime import call_skill


def clean(leads):
    """Clean a list of leads. Each lead = {"email": ..., "phone": ..., "name": ...}"""
    try:
        if isinstance(leads, dict) and "rows" in leads:
            leads = leads["rows"]
        if not isinstance(leads, list):
            return {"error": "Expected a list of leads or {'rows': [...]}"}

        results = []
        for lead in leads:
            row = {"original": lead}

            # 1. Validate email
            email = lead.get("email", "")
            if email:
                row["email_valid"] = call_skill("python-email-validator", {"email": email})

            # 2. Check disposable
            if email:
                row["email_disposable"] = call_skill("disposable-email-check", {"email": email})

            # 3. Parse phone
            phone = lead.get("phone", "")
            if phone:
                row["phone_parsed"] = call_skill("python-phonenumbers", {"phone": phone})

            # 4. Scrub PII from name/notes
            text = lead.get("notes", "") or lead.get("name", "")
            if text:
                row["pii_scrubbed"] = call_skill("pii-scrub", {"text": text})

            # Score: simple pass/fail
            email_ok = row.get("email_valid", {}).get("valid", False) if email else True
            not_disposable = not row.get("email_disposable", {}).get("is_disposable", False) if email else True
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
