import bcrypt


def hash(password):
    try:
        pw = password.encode("utf-8")
        hashed = bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")
        return {"hash": hashed}
    except Exception as e:
        return {"error": str(e)}


def verify(password, hashed):
    try:
        result = bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        return {"valid": result}
    except Exception as e:
        return {"error": str(e)}
