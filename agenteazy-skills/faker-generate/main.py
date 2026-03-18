from faker import Faker


def generate(field="name", locale="en_US"):
    try:
        return Faker(locale).format(field)
    except Exception as e:
        return {"error": str(e)}
