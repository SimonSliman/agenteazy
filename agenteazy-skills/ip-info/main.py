import ipaddress


def info(ip):
    try:
        addr = ipaddress.ip_address(ip)
        return {"ip": str(addr), "version": addr.version, "is_private": addr.is_private, "is_global": addr.is_global, "is_loopback": addr.is_loopback, "is_multicast": addr.is_multicast}
    except Exception as e:
        return {"error": str(e)}
