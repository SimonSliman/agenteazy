


def dedupe(items):
    try:
        if isinstance(items, str):
            import json
            items = json.loads(items)
        seen = set()
        unique = []
        for item in items:
            key = str(item)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return {'unique': unique, 'original_count': len(items), 'unique_count': len(unique), 'duplicates_removed': len(items) - len(unique)}
    except Exception as e:
        return {"error": str(e)}
