import toml


def parse(toml_string):
    try:
        data = toml.loads(toml_string)
        return {"parsed": data, "type": type(data).__name__}
    except Exception as e:
        return {"error": str(e)}
