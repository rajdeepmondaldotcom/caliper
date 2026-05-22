"""Small humanization helpers — formatting and redaction."""

from __future__ import annotations

import datetime as dt
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


def human_datetime(
    value: dt.datetime | None,
    timezone: str = "UTC",
    *,
    fallback: str = "",
) -> str:
    """Format a timestamp as a readable, traceable local session label."""

    if value is None:
        return fallback
    from caliper.timeutil import load_timezone

    local = value.astimezone(load_timezone(timezone))
    hour = local.strftime("%I").lstrip("0") or "0"
    minute = local.strftime("%M")
    ampm = local.strftime("%p").lower()
    return f"{hour}:{minute} {ampm}, {local:%A} {local.day} {local:%B} {local.year}"


def session_display_label(
    event: Any,
    timezone: str = "UTC",
    *,
    include_title: bool = False,
) -> str:
    """Return the human-facing label for a usage event's session."""

    fallback = str(
        getattr(event, "session_id", "") or getattr(getattr(event, "path", None), "stem", "")
    )
    label = human_datetime(getattr(event, "timestamp", None), timezone, fallback=fallback)
    if not include_title:
        return label
    thread = getattr(event, "thread", None)
    title = str(
        getattr(thread, "title", "") or getattr(thread, "first_user_message", "") or ""
    ).strip()
    return f"{label} | {redact(title, show=True, limit=72)}" if title else label


def session_label_lookup(events: Any, timezone: str = "UTC") -> dict[str, str]:
    """Map raw session IDs to first-seen human labels."""

    first_by_id: dict[str, Any] = {}
    for event in events:
        session_id = str(getattr(event, "session_id", "") or "")
        if not session_id:
            continue
        current = first_by_id.get(session_id)
        timestamp = getattr(event, "timestamp", None)
        if current is None or (
            isinstance(timestamp, dt.datetime)
            and isinstance(getattr(current, "timestamp", None), dt.datetime)
            and timestamp < current.timestamp
        ):
            first_by_id[session_id] = event
    return {
        session_id: session_display_label(event, timezone)
        for session_id, event in first_by_id.items()
    }


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
