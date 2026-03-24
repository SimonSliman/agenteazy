from disposable_email_domains import blocklist


def check(email):
    try:
        if "@" not in email:
            return {"error": "Invalid email format - missing @"}
        domain = email.strip().lower().split("@")[-1]
        is_disposable = domain in blocklist
        return {"email": email, "domain": domain, "is_disposable": is_disposable, "blocklist_size": len(blocklist)}
    except Exception as e:
        return {"error": str(e)}
