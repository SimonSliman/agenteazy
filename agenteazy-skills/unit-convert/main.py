import pint
ureg = pint.UnitRegistry()


def convert(value, from_unit, to_unit):
    try:
        quantity = float(value) * ureg(from_unit)
        result = quantity.to(to_unit)
        return {"value": result.magnitude, "unit": str(result.units), "original": {"value": float(value), "unit": from_unit}}
    except Exception as e:
        return {"error": str(e)}
