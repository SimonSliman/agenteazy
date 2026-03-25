import difflib


def diff(text1, text2):
    try:
        d = difflib.unified_diff(text1.splitlines(), text2.splitlines(), lineterm='')
        diff_lines = list(d)
        return {'diff': '\n'.join(diff_lines), 'lines_changed': len([l for l in diff_lines if l.startswith('+') or l.startswith('-')])}
    except Exception as e:
        return {"error": str(e)}
