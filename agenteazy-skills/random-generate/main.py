import random
import string


def generate(type="string", length=16, min_val=0, max_val=100):
    try:
        if type == 'string':
            return {'result': ''.join(random.choices(string.ascii_letters + string.digits, k=int(length)))}
        elif type == 'int':
            return {'result': random.randint(int(min_val), int(max_val))}
        elif type == 'float':
            return {'result': round(random.uniform(float(min_val), float(max_val)), 4)}
        elif type == 'hex':
            return {'result': ''.join(random.choices('0123456789abcdef', k=int(length)))}
        else:
            return {'error': f'Unknown type: {type}'}
    except Exception as e:
        return {"error": str(e)}
