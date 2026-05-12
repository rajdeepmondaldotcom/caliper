"""Small humanization helpers — formatting and redaction."""

from __future__ import annotations

REDACTION_LIMIT = 72


def format_int(value: int) -> str:
    return f"{value:,}"


def redact(text: str, show: bool, limit: int = REDACTION_LIMIT) -> str:
    """Collapse whitespace; truncate with ellipsis when `show` is False."""
    clean = " ".join(str(text).split())
    if show or not clean or len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."
