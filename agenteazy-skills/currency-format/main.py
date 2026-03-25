from babel.numbers import format_currency


def format(amount, currency="USD", locale="en_US"):
    try:
        formatted = format_currency(float(amount), currency, locale=locale)
        return {"formatted": formatted, "amount": float(amount), "currency": currency, "locale": locale}
    except Exception as e:
        return {"error": str(e)}
