from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def local_timezone() -> dt.tzinfo:
    return dt.datetime.now().astimezone().tzinfo or dt.UTC


def load_timezone(name: str | None) -> dt.tzinfo:
    if not name or name == "local":
        return local_timezone()
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {name}") from exc


def parse_datetime(value: str | None, default: dt.datetime | None = None) -> dt.datetime:
    if not value:
        if default is None:
            raise ValueError("missing datetime")
        return default

    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    if len(raw) == 8 and raw.isdigit():
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]} 00:00:00"
    elif len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        raw = raw + " 00:00:00"

    parsed = dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_timezone())
    return parsed


def parse_event_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def day_key(value: dt.datetime, tz: dt.tzinfo) -> str:
    return value.astimezone(tz).strftime("%Y-%m-%d")


def month_key(value: dt.datetime, tz: dt.tzinfo) -> str:
    return value.astimezone(tz).strftime("%Y-%m")


def week_key(value: dt.datetime, tz: dt.tzinfo) -> str:
    local = value.astimezone(tz)
    year, week, _ = local.isocalendar()
    return f"{year}-W{week:02d}"


def window_label(start: dt.datetime, end: dt.datetime, tzname: str) -> str:
    tz = load_timezone(tzname)
    start_label = start.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    end_label = end.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    return f"{start_label} to {end_label}"
