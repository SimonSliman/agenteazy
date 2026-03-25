import re


def count(text):
    try:
        words = text.split()
        chars = len(text)
        sentences = len(re.split(r'[.!?]+', text))
        paragraphs = len([p for p in text.split('\n\n') if p.strip()])
        return {'words': len(words), 'characters': chars, 'sentences': sentences, 'paragraphs': paragraphs}
    except Exception as e:
        return {"error": str(e)}
