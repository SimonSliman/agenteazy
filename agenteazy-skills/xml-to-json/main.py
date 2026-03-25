import xmltodict
import json


def convert(xml_string):
    try:
        data = xmltodict.parse(xml_string)
        return {'json': json.loads(json.dumps(data)), 'keys': list(data.keys())}
    except Exception as e:
        return {"error": str(e)}
