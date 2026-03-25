import re
from agenteazy_runtime import call_skill

EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
FREE_PROVIDERS = {"gmail.com","yahoo.com","hotmail.com","outlook.com","aol.com","icloud.com","protonmail.com","mail.com","zoho.com","yandex.com","gmx.com","live.com"}


def _safe_call(skill, data):
    try:
        result = call_skill(skill, data)
        if not isinstance(result, dict):
            return {"raw": str(result)}
        return result
    except Exception as e:
        return {"error": str(e)}


def qualify(leads):
    """Score and qualify a list of leads."""
    try:
        if isinstance(leads, dict) and "rows" in leads:
            leads = leads["rows"]
        if not isinstance(leads, list):
            return {"error": "Expected a list of leads or {'rows': [...]}"}

        results = []
        for lead in leads:
            row = {"original": lead}
            score = 0
            flags = []

            email = lead.get("email", "")
            if email:
                if EMAIL_RE.match(email.strip()):
                    score += 20
                else:
                    flags.append("invalid_email")

                disp = _safe_call("disposable-email-check", {"email": email})
                row["disposable_check"] = disp
                if disp.get("is_disposable"):
                    flags.append("disposable_email")
                    score -= 30
                else:
                    score += 10

                domain_info = _safe_call("domain-extract", {"url": email.split("@")[-1]})
                row["domain_info"] = domain_info
                domain = domain_info.get("registered_domain", "")
                if domain.lower() in FREE_PROVIDERS:
                    flags.append("free_email_provider")
                else:
                    score += 30
                    flags.append("business_email")
            else:
                flags.append("no_email")
                score -= 20

            phone = lead.get("phone", "")
            if phone:
                parsed = _safe_call("python-phonenumbers", {"number": phone})
                row["phone_parsed"] = parsed
                if parsed.get("error"):
                    flags.append("invalid_phone")
                else:
                    score += 20
                    flags.append("valid_phone")
            else:
                flags.append("no_phone")

            if lead.get("company"):
                score += 10
                flags.append("has_company")

            score = max(0, min(100, score))
            if score >= 70:
                tier = "hot"
            elif score >= 40:
                tier = "warm"
            else:
                tier = "cold"

            row["score"] = score
            row["tier"] = tier
            row["flags"] = flags
            results.append(row)

        hot = sum(1 for r in results if r["tier"] == "hot")
        warm = sum(1 for r in results if r["tier"] == "warm")
        cold = sum(1 for r in results if r["tier"] == "cold")
        return {"total": len(results), "hot": hot, "warm": warm, "cold": cold, "results": results}
    except Exception as e:
        return {"error": str(e)}
