import pycountry


def lookup(query):
    try:
        c = pycountry.countries.lookup(query)
        return {'name': c.name, 'alpha_2': c.alpha_2, 'alpha_3': c.alpha_3, 'numeric': c.numeric, 'official_name': getattr(c, 'official_name', None)}
    except Exception as e:
        return {"error": str(e)}
