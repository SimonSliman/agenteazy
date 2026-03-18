import hashlib


SUPPORTED_ALGORITHMS = {"sha256", "sha512", "md5", "sha1"}


def hash(text: str, algorithm: str = "sha256") -> str:
    try:
        if algorithm not in SUPPORTED_ALGORITHMS:
            return {"error": f"Unsupported algorithm: {algorithm}. Supported: {', '.join(sorted(SUPPORTED_ALGORITHMS))}"}
        h = hashlib.new(algorithm)
        h.update(text.encode("utf-8"))
        return h.hexdigest()
    except Exception as e:
        return {"error": str(e)}
