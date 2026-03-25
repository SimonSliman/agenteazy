import hashlib


def hash_all(text):
    try:
        b = text.encode('utf-8')
        return {'md5': hashlib.md5(b).hexdigest(), 'sha1': hashlib.sha1(b).hexdigest(), 'sha256': hashlib.sha256(b).hexdigest(), 'sha512': hashlib.sha512(b).hexdigest()}
    except Exception as e:
        return {"error": str(e)}
