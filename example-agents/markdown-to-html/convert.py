"""Convert Markdown text to clean HTML."""

import markdown


def convert(markdown_text: str) -> str:
    """Convert a Markdown string to HTML.

    Args:
        markdown_text: Raw Markdown content.

    Returns:
        Rendered HTML string.
    """
    try:
        return markdown.markdown(
            markdown_text,
            extensions=["extra", "codehilite", "toc"],
        )
    except Exception as e:
        return f"<p>Error converting markdown: {e}</p>"
