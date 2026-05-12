from __future__ import annotations

import datetime as dt

import pytest

from codex_meter.intervals import parse_interval

NOW = dt.datetime(2026, 5, 12, 15, 30, tzinfo=dt.UTC)  # Tuesday


def test_today() -> None:
    interval = parse_interval("today", NOW)
    assert interval.start == dt.datetime(2026, 5, 12, tzinfo=dt.UTC)
    assert interval.end == NOW


def test_yesterday() -> None:
    interval = parse_interval("yesterday", NOW)
    assert interval.start == dt.datetime(2026, 5, 11, tzinfo=dt.UTC)
    assert interval.end == dt.datetime(2026, 5, 12, tzinfo=dt.UTC)


def test_last_n_days_anchors_on_now() -> None:
    interval = parse_interval("last 7 days", NOW)
    assert interval.end == NOW
    assert interval.start == NOW - dt.timedelta(days=7)


def test_previous_n_days_is_the_window_before_last_n_days() -> None:
    last = parse_interval("last 7 days", NOW)
    previous = parse_interval("previous 7 days", NOW)
    assert previous.end == last.start
    assert previous.start == last.start - dt.timedelta(days=7)


def test_last_n_hours() -> None:
    interval = parse_interval("last 4 hours", NOW)
    assert interval.start == NOW - dt.timedelta(hours=4)
    assert interval.end == NOW


def test_this_month_starts_first_of_month() -> None:
    interval = parse_interval("this month", NOW)
    assert interval.start == dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
    assert interval.end == NOW


def test_last_month_spans_previous_calendar_month() -> None:
    interval = parse_interval("last month", NOW)
    assert interval.start == dt.datetime(2026, 4, 1, tzinfo=dt.UTC)
    assert interval.end == dt.datetime(2026, 5, 1, tzinfo=dt.UTC)


def test_this_week_starts_monday() -> None:
    interval = parse_interval("this week", NOW)
    # Tuesday May 12 → Monday May 11
    assert interval.start == dt.datetime(2026, 5, 11, tzinfo=dt.UTC)
    assert interval.end == NOW


def test_iso_date_spans_24h() -> None:
    interval = parse_interval("2026-05-01", NOW)
    assert interval.start == dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
    assert interval.end == dt.datetime(2026, 5, 1, 23, 59, 59, tzinfo=dt.UTC)


def test_iso_range() -> None:
    interval = parse_interval("2026-05-01..2026-05-08", NOW)
    assert interval.start == dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
    assert interval.end == dt.datetime(2026, 5, 8, 23, 59, 59, tzinfo=dt.UTC)


def test_empty_expression_rejected() -> None:
    with pytest.raises(ValueError):
        parse_interval("", NOW)


def test_unknown_expression_rejected() -> None:
    with pytest.raises(ValueError):
        parse_interval("nonsense", NOW)
