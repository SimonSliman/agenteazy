"""Simple text translation stub with language detection."""


# Basic word maps for demonstration
_TRANSLATIONS = {
    "es": {"hello": "hola", "world": "mundo", "the": "el", "is": "es",
           "good": "bueno", "bad": "malo", "yes": "sí", "no": "no",
           "thank": "gracias", "please": "por favor", "code": "código"},
    "fr": {"hello": "bonjour", "world": "monde", "the": "le", "is": "est",
           "good": "bon", "bad": "mauvais", "yes": "oui", "no": "non",
           "thank": "merci", "please": "s'il vous plaît", "code": "code"},
    "de": {"hello": "hallo", "world": "welt", "the": "die", "is": "ist",
           "good": "gut", "bad": "schlecht", "yes": "ja", "no": "nein",
           "thank": "danke", "please": "bitte", "code": "code"},
}


def translate(text: str, target_lang: str = "es") -> str:
    """Translate text to a target language using simple word substitution.

    Args:
        text: Input text in English.
        target_lang: Target language code (es, fr, de).

    Returns:
        Translated text (best-effort word substitution).
    """
    lang_map = _TRANSLATIONS.get(target_lang.lower())
    if not lang_map:
        return f"[Unsupported language: {target_lang}. Supported: es, fr, de]"

    words = text.split()
    translated = [lang_map.get(w.lower().strip(".,!?"), w) for w in words]
    return " ".join(translated)
