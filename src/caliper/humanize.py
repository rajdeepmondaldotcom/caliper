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


_SPARKLINE_BARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    """Render a list of numbers as a Unicode block sparkline.

    Returns the empty string for an empty input. All-equal inputs render
    as the lowest bar repeated. Used by ``caliper live``, ``caliper
    forecast``, and the Textual TUI.
    """
    if not values:
        return ""
    low = min(values)
    high = max(values)
    if high == low:
        return _SPARKLINE_BARS[0] * len(values)
    span = high - low
    last = len(_SPARKLINE_BARS) - 1
    return "".join(_SPARKLINE_BARS[round((value - low) / span * last)] for value in values)
