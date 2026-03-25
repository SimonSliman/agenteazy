import humanize


def format(bytes_val):
    try:
        b = int(bytes_val)
        return {'natural': humanize.naturalsize(b), 'binary': humanize.naturalsize(b, binary=True), 'bytes': b}
    except Exception as e:
        return {"error": str(e)}
