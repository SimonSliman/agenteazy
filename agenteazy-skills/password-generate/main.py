import secrets
import string


def generate(length: int = 16, uppercase: bool = True, digits: bool = True, special: bool = True) -> str:
    try:
        chars = string.ascii_lowercase
        if uppercase:
            chars += string.ascii_uppercase
        if digits:
            chars += string.digits
        if special:
            chars += string.punctuation
        return "".join(secrets.choice(chars) for _ in range(length))
    except Exception as e:
        return {"error": str(e)}
