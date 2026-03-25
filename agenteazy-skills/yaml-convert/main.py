import yaml
import json


def parse(yaml_string):
    try:
        data = yaml.safe_load(yaml_string)
        return {"parsed": data, "type": type(data).__name__}
    except Exception as e:
        return {"error": str(e)}
