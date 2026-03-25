import textstat


def score(text):
    try:
        return {
            "flesch_reading_ease": textstat.flesch_reading_ease(text),
            "flesch_kincaid_grade": textstat.flesch_kincaid_grade(text),
            "gunning_fog": textstat.gunning_fog(text),
            "smog_index": textstat.smog_index(text),
            "coleman_liau": textstat.coleman_liau_index(text),
            "automated_readability": textstat.automated_readability_index(text),
            "dale_chall": textstat.dale_chall_readability_score(text),
            "reading_time_seconds": textstat.reading_time(text, ms_per_char=14.69),
            "word_count": textstat.lexicon_count(text),
            "sentence_count": textstat.sentence_count(text),
        }
    except Exception as e:
        return {"error": str(e)}
