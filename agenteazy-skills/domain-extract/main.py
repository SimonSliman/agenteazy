import tldextract


def extract(url):
    try:
        r = tldextract.extract(url)
        return {
            "url": url,
            "subdomain": r.subdomain,
            "domain": r.domain,
            "suffix": r.suffix,
            "registered_domain": r.registered_domain,
            "fqdn": r.fqdn,
            "is_private": r.is_private,
        }
    except Exception as e:
        return {"error": str(e)}
