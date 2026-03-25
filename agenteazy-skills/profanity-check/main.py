from better_profanity import profanity


def check(text):
    try:
        profanity.load_censor_words()
        is_profane = profanity.contains_profanity(text)
        censored = profanity.censor(text)
        return {
            "text": text[:200],
            "is_profane": is_profane,
            "censored": censored,
        }
    except Exception as e:
        return {"error": str(e)}
