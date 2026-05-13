from __future__ import annotations

import datetime as dt

import pytest

from caliper.timeutil import load_timezone, parse_datetime, parse_event_timestamp, window_label


def test_load_timezone_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unknown IANA timezone"):
        load_timezone("Not/AZone")


def test_parse_datetime_requires_value_without_default() -> None:
    with pytest.raises(ValueError, match="missing datetime"):
        parse_datetime(None)


def test_parse_datetime_accepts_compact_date() -> None:
    parsed = parse_datetime("20260513")

    assert parsed.year == 2026
    assert parsed.month == 5
    assert parsed.day == 13


def test_parse_event_timestamp_handles_empty_invalid_and_naive_values() -> None:
    assert parse_event_timestamp(None) is None
    assert parse_event_timestamp("not a timestamp") is None

    parsed = parse_event_timestamp("2026-05-13T12:00:00")

    assert parsed == dt.datetime(2026, 5, 13, 12, tzinfo=dt.UTC)


def test_window_label_uses_requested_timezone() -> None:
    start = dt.datetime(2026, 5, 13, 0, tzinfo=dt.UTC)
    end = dt.datetime(2026, 5, 13, 1, tzinfo=dt.UTC)

    assert "UTC" in window_label(start, end, "UTC")
