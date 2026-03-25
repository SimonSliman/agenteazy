from faker import Faker


def profile(locale="en_US"):
    try:
        fake = Faker(locale)
        p = fake.profile()
        p["birthdate"] = str(p.get("birthdate", ""))
        return p
    except Exception as e:
        return {"error": str(e)}
