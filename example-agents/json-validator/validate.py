"""Validate JSON strings, optionally against a JSON Schema."""

import json

import jsonschema


def validate(json_string: str, schema: dict = None) -> dict:
    """Validate a JSON string and optionally check it against a schema.

    Args:
        json_string: Raw JSON string to validate.
        schema: Optional JSON Schema dict to validate against.

    Returns:
        Dict with 'valid' bool and 'errors' list.
    """
    errors = []
    try:
        data = json.loads(json_string)
    except (json.JSONDecodeError, TypeError) as e:
        return {"valid": False, "errors": [f"Invalid JSON: {e}"], "data": None}

    if schema:
        validator = jsonschema.Draft7Validator(schema)
        errors = [
            {"path": list(err.absolute_path), "message": err.message}
            for err in validator.iter_errors(data)
        ]

    return {"valid": len(errors) == 0, "errors": errors, "data": data}
