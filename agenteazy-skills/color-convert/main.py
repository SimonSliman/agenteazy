from colour import Color


def convert(color, to_format="hex"):
    try:
        c = Color(color)
        return {'hex': c.hex_l, 'rgb': list(c.rgb), 'hsl': list(c.hsl), 'web': c.web}
    except Exception as e:
        return {"error": str(e)}
