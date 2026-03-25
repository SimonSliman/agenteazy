def _flatten(obj, parent_key='', sep='.'):
    items = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f'{parent_key}{sep}{k}' if parent_key else k
            items.extend(_flatten(v, new_key, sep).items())
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_key = f'{parent_key}{sep}{i}' if parent_key else str(i)
            items.extend(_flatten(v, new_key, sep).items())
    else:
        items.append((parent_key, obj))
    return dict(items)


def flatten(data):
    try:
        if isinstance(data, str):
            import json
            data = json.loads(data)
        result = _flatten(data)
        return {'flattened': result, 'keys': len(result)}
    except Exception as e:
        return {"error": str(e)}
