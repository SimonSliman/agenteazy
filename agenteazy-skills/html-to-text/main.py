from bs4 import BeautifulSoup


def extract(html):
    try:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        return {"text": text, "length": len(text)}
    except Exception as e:
        return {"error": str(e)}
