import yaml
import json


def convert(json_string):
    try:
        data = json.loads(json_string) if isinstance(json_string, str) else json_string
        yaml_str = yaml.dump(data, default_flow_style=False)
        return {'yaml': yaml_str}
    except Exception as e:
        return {"error": str(e)}
