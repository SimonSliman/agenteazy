import jwt


def decode(token, verify_signature=False):
    try:
        options = {"verify_signature": False} if not verify_signature else {}
        data = jwt.decode(token, algorithms=["HS256", "RS256", "ES256"], options=options)
        header = jwt.get_unverified_header(token)
        return {"header": header, "payload": data}
    except Exception as e:
        return {"error": str(e)}
