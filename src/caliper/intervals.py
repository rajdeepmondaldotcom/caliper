"""Natural-language window expressions: 'last 7 days', 'yesterday', 'this month', etc."""

from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass

WINDOW_EXAMPLES = "Try: 'last 7 days', 'previous 7 days', 'this week', '2026-05-01..2026-05-12'."


@dataclass(frozen=True)
class Interval:
    start: dt.datetime
    end: dt.datetime
    label: str


_LAST_N_DAYS = re.compile(r"^last\s+(\d+)\s+days?$")
_PREVIOUS_N_DAYS = re.compile(r"^previous\s+(\d+)\s+days?$")
_LAST_N_HOURS = re.compile(r"^last\s+(\d+)\s+hours?$")


def _start_of_day(when: dt.datetime) -> dt.datetime:
    return when.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_week(when: dt.datetime) -> dt.datetime:
    monday = when - dt.timedelta(days=when.weekday())
    return _start_of_day(monday)


def _start_of_month(when: dt.datetime) -> dt.datetime:
    return _start_of_day(when.replace(day=1))


def _end_of_month(when: dt.datetime) -> dt.datetime:
    last_day = calendar.monthrange(when.year, when.month)[1]
    return when.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)


def parse_interval(expression: str, now: dt.datetime) -> Interval:
    """Parse a window expression relative to `now`. Returns an Interval [start, end).

    Supported forms (case-insensitive):
    - "today", "yesterday"
    - "this week", "last week", "previous week"
    - "this month", "last month", "previous month"
    - "last N days", "previous N days"
    - "last N hours"
    - ISO date "YYYY-MM-DD" (24h spanning that local day)
    - ISO range "YYYY-MM-DD..YYYY-MM-DD" (24h spans inclusive)
    """
    if not expression:
        raise ValueError("window expression must be non-empty")
    raw = expression.strip().lower()

    named = _named_interval(raw, now)
    if named is not None:
        return named

    relative = _relative_interval(raw, now)
    if relative is not None:
        return relative

    return _iso_interval(raw, now)


def _named_interval(raw: str, now: dt.datetime) -> Interval | None:
    if raw == "today":
        start = _start_of_day(now)
        return Interval(start=start, end=now, label="today")
    if raw == "yesterday":
        start = _start_of_day(now) - dt.timedelta(days=1)
        end = _start_of_day(now)
        return Interval(start=start, end=end, label="yesterday")
    if raw == "this week":
        return Interval(start=_start_of_week(now), end=now, label="this week")
    if raw in {"last week", "previous week"}:
        this_week = _start_of_week(now)
        start = this_week - dt.timedelta(days=7)
        return Interval(start=start, end=this_week, label="last week")
    if raw == "this month":
        return Interval(start=_start_of_month(now), end=now, label="this month")
    if raw in {"last month", "previous month"}:
        this_month = _start_of_month(now)
        prev_end = this_month
        prev_start = (this_month - dt.timedelta(days=1)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return Interval(start=prev_start, end=prev_end, label="last month")
    return None


def _relative_interval(raw: str, now: dt.datetime) -> Interval | None:
    match = _LAST_N_DAYS.match(raw)
    if match:
        days = int(match.group(1))
        return Interval(start=now - dt.timedelta(days=days), end=now, label=raw)

    match = _PREVIOUS_N_DAYS.match(raw)
    if match:
        days = int(match.group(1))
        anchor = now - dt.timedelta(days=days)
        return Interval(start=anchor - dt.timedelta(days=days), end=anchor, label=raw)

    match = _LAST_N_HOURS.match(raw)
    if match:
        hours = int(match.group(1))
        return Interval(start=now - dt.timedelta(hours=hours), end=now, label=raw)
    return None


def _iso_interval(raw: str, now: dt.datetime) -> Interval:
    if ".." in raw:
        left, _, right = raw.partition("..")
        return Interval(
            start=_iso_to_dt(left, now.tzinfo, end_of_day=False),
            end=_iso_to_dt(right, now.tzinfo, end_of_day=True),
            label=raw,
        )

    return Interval(
        start=_iso_to_dt(raw, now.tzinfo, end_of_day=False),
        end=_iso_to_dt(raw, now.tzinfo, end_of_day=True),
        label=raw,
    )


def _iso_to_dt(raw: str, tz: dt.tzinfo | None, *, end_of_day: bool) -> dt.datetime:
    text = _iso_text_with_boundary(raw, end_of_day=end_of_day)
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Unrecognized window expression: {raw!r}. {WINDOW_EXAMPLES}") from exc
    return _with_timezone(parsed, tz)


def _iso_text_with_boundary(raw: str, *, end_of_day: bool) -> str:
    text = raw.strip()
    boundary = "23:59:59" if end_of_day else "00:00:00"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text} {boundary}"
    if len(text) == 8 and text.isdigit():
        head = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return f"{head} {boundary}"
    return text


def _with_timezone(parsed: dt.datetime, tz: dt.tzinfo | None) -> dt.datetime:
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz or dt.UTC)
    return parsed


_MONTH_END_MIN = _end_of_month  # re-export keeps `end_of_month` discoverable
