"""Small humanization helpers — formatting and redaction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

REDACTION_LIMIT = 72


def format_int(value: int) -> str:
    return f"{value:,}"


def compact_number(value: Any, prefix: str = "") -> str:
    numeric = float(value)
    sign = "-" if numeric < 0 else ""
    amount = abs(numeric)
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if amount >= threshold:
            return f"{sign}{prefix}{amount / threshold:.3g}{suffix}"
    if amount.is_integer():
        return f"{sign}{prefix}{int(amount):,}"
    return f"{sign}{prefix}{amount:,.2f}"


def redact(text: str, show: bool, limit: int = REDACTION_LIMIT) -> str:
    """Collapse whitespace; truncate with ellipsis when `show` is False."""
    clean = " ".join(str(text).split())
    if show or not clean or len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def short_table_label(text: str) -> str:
    """Prefer scannable labels for dense terminal tables."""
    clean = " ".join(str(text).split())
    if clean.startswith(("/", "~")):
        return Path(clean).name or clean
    return clean
