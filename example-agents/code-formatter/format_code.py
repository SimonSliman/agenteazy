"""Format Python code using Black."""

import black


def format(code: str, language: str = "python") -> str:
    """Format source code.

    Args:
        code: Raw source code string.
        language: Programming language (currently only 'python' supported).

    Returns:
        Formatted code string, or error message.
    """
    if language.lower() != "python":
        return f"# Unsupported language: {language}. Only Python is supported.\n{code}"

    try:
        mode = black.Mode(line_length=88, target_versions={black.TargetVersion.PY310})
        return black.format_str(code, mode=mode)
    except black.NothingChanged:
        return code
    except Exception as e:
        return f"# Formatting error: {e}\n{code}"
