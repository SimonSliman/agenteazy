import base64


def encode(text, encoding="base64"):
    try:
        if encoding == 'base64':
            return {'encoded': base64.b64encode(text.encode()).decode()}
        elif encoding == 'base32':
            return {'encoded': base64.b32encode(text.encode()).decode()}
        elif encoding == 'base16':
            return {'encoded': base64.b16encode(text.encode()).decode()}
        else:
            return {'error': f'Unknown encoding: {encoding}'}
    except Exception as e:
        return {"error": str(e)}
