import base64


def decode(encoded, encoding="base64"):
    try:
        if encoding == 'base64':
            return {'decoded': base64.b64decode(encoded).decode()}
        elif encoding == 'base32':
            return {'decoded': base64.b32decode(encoded).decode()}
        elif encoding == 'base16':
            return {'decoded': base64.b16decode(encoded).decode()}
        else:
            return {'error': f'Unknown encoding: {encoding}'}
    except Exception as e:
        return {"error": str(e)}
