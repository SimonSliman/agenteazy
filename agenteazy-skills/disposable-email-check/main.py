from disposable_email_domains import blocklist


def check(email):
    try:
        if "@" not in email:
            return {"error": "Invalid email format - missing @"}
        domain = email.strip().lower().split("@")[-1]
        return {"email": email, "domain": domain, "is_disposable": domain in blocklist, "blocklist_size": len(blocklist)}
    except Exception as e:
        return {"error": str(e)}
