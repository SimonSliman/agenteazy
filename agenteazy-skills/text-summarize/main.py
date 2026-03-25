from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer


def summarize(text, sentences=3):
    try:
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = LsaSummarizer()
        summary = summarizer(parser.document, int(sentences))
        result = " ".join(str(s) for s in summary)
        return {"summary": result, "sentence_count": len(list(summary)), "original_length": len(text)}
    except Exception as e:
        return {"error": str(e)}
