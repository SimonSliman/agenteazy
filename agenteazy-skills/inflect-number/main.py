import inflect
_p = inflect.engine()


def convert(number, to="words"):
    try:
        if to == 'words':
            return {'result': _p.number_to_words(number)}
        elif to == 'ordinal':
            return {'result': _p.ordinal(number)}
        else:
            return {'result': _p.number_to_words(number)}
    except Exception as e:
        return {"error": str(e)}
