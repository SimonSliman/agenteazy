import mimetypes


def detect(filename):
    try:
        mime_type, encoding = mimetypes.guess_type(filename)
        return {'filename': filename, 'mime_type': mime_type, 'encoding': encoding}
    except Exception as e:
        return {"error": str(e)}
