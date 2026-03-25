import ftfy
import re


def clean(text):
    try:
        cleaned = ftfy.fix_text(text)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return {'cleaned': cleaned, 'original_length': len(text), 'cleaned_length': len(cleaned)}
    except Exception as e:
        return {"error": str(e)}
