import json


def validate(json_string):
    try:
        data = json.loads(json_string)
        return {'valid': True, 'type': type(data).__name__, 'keys': list(data.keys()) if isinstance(data, dict) else None}
    except Exception as e:
        return {"error": str(e)}
