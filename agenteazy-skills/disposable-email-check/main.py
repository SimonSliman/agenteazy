from disposable_email_domains import blocklist


def check(email):
    domain = email.rsplit("@", 1)[-1].lower()
    is_disposable = domain in blocklist
    return {
        "email": email,
        "domain": domain,
        "is_disposable": is_disposable,
        "blocklist_size": len(blocklist),
    }
