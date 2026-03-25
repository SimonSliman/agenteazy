import uuid


def generate(version=4):
    try:
        v = int(version)
        if v == 1:
            return {'uuid': str(uuid.uuid1())}
        elif v == 4:
            return {'uuid': str(uuid.uuid4())}
        else:
            return {'error': 'Supported versions: 1, 4'}
    except Exception as e:
        return {"error": str(e)}
