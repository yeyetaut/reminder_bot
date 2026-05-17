def escape_md(text: str | None) -> str:
    """Escape special characters for Telegram Markdown V1."""
    if not text:
        return ""
    # In Markdown V1, characters _, *, `, [ need to be escaped.
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")
