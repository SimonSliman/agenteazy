import yaml
import json


def convert(yaml_string):
    try:
        data = yaml.safe_load(yaml_string)
        return {'json': data}
    except Exception as e:
        return {"error": str(e)}
