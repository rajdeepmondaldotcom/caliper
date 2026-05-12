from __future__ import annotations

import datetime as dt
from pathlib import Path

from codex_meter.models import RateLimitSample
from codex_meter.windows import (
    compute_window_state,
    format_burn_rate,
    format_seconds_remaining,
)


def _sample(
    when: dt.datetime,
    primary: float | None = None,
    secondary: float | None = None,
    primary_window: int | None = None,
    secondary_window: int | None = None,
    primary_resets_at: object = None,
    secondary_resets_at: object = None,
) -> RateLimitSample:
    return RateLimitSample(
        timestamp=when,
        path=Path("/tmp/example.jsonl"),
        session_id="example",
        primary_used_percent=primary,
        secondary_used_percent=secondary,
        primary_window_minutes=primary_window,
        secondary_window_minutes=secondary_window,
        primary_resets_at=primary_resets_at,
        secondary_resets_at=secondary_resets_at,
    )


def test_empty_samples_yield_blank_state() -> None:
    now = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    state = compute_window_state([], now, "primary")
    assert state.used_percent is None
    assert state.burn_rate_per_hour is None
    assert state.samples == 0


def test_unknown_window_label_raises() -> None:
    import pytest

    now = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    with pytest.raises(ValueError):
        compute_window_state([], now, "tertiary")


def test_resets_at_decoded_from_unix_epoch() -> None:
    now = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    reset_epoch = int((now + dt.timedelta(hours=2)).timestamp())
    sample = _sample(when=now, primary=42.0, primary_window=300, primary_resets_at=reset_epoch)
    state = compute_window_state([sample], now, "primary")
    assert state.used_percent == 42.0
    assert state.window_minutes == 300
    assert state.reset_at is not None
    assert state.reset_at.tzinfo is not None
    assert 7195 <= (state.seconds_remaining or 0) <= 7200


def test_burn_rate_requires_three_recent_samples() -> None:
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    samples = [
        _sample(when=base, primary=10.0),
        _sample(when=base + dt.timedelta(hours=1), primary=20.0),
        _sample(when=base + dt.timedelta(hours=2), primary=30.0),
    ]
    state = compute_window_state(samples, base + dt.timedelta(hours=2), "primary")
    assert state.burn_rate_per_hour is not None
    assert round(state.burn_rate_per_hour, 2) == 10.0


def test_burn_rate_projects_eta_to_full() -> None:
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    samples = [
        _sample(when=base, primary=20.0),
        _sample(when=base + dt.timedelta(hours=1), primary=40.0),
        _sample(when=base + dt.timedelta(hours=2), primary=60.0),
    ]
    now = base + dt.timedelta(hours=2)
    state = compute_window_state(samples, now, "primary")
    assert state.burn_rate_per_hour is not None
    # 20%/hour, 40% left → 2 hours to 100%
    assert state.eta_to_100 is not None
    delta = state.eta_to_100 - now
    assert 7100 <= delta.total_seconds() <= 7300


def test_burn_rate_none_when_under_three_samples() -> None:
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    samples = [
        _sample(when=base, primary=10.0),
        _sample(when=base + dt.timedelta(minutes=30), primary=20.0),
    ]
    state = compute_window_state(samples, base + dt.timedelta(minutes=30), "primary")
    assert state.burn_rate_per_hour is None
    assert state.eta_to_100 is None


def test_eta_omitted_when_already_at_or_above_100() -> None:
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    samples = [
        _sample(when=base, primary=80.0),
        _sample(when=base + dt.timedelta(hours=1), primary=90.0),
        _sample(when=base + dt.timedelta(hours=2), primary=100.0),
    ]
    state = compute_window_state(samples, base + dt.timedelta(hours=2), "primary")
    assert state.eta_to_100 is None


def test_seconds_remaining_clamped_at_zero() -> None:
    now = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    past_epoch = int((now - dt.timedelta(hours=1)).timestamp())
    sample = _sample(when=now, primary=50.0, primary_resets_at=past_epoch)
    state = compute_window_state([sample], now, "primary")
    assert state.seconds_remaining == 0


def test_format_seconds_remaining_branches() -> None:
    assert format_seconds_remaining(None) == "—"
    assert format_seconds_remaining(-5) == "0s"
    assert format_seconds_remaining(45) == "45s"
    assert format_seconds_remaining(125) == "2m 05s"
    assert format_seconds_remaining(3725) == "1h 02m 05s"


def test_format_burn_rate_branches() -> None:
    assert format_burn_rate(None) == "—"
    assert format_burn_rate(0.0) == "+0.00%/h"
    assert format_burn_rate(12.345) == "+12.35%/h"
    assert format_burn_rate(-3.0) == "-3.00%/h"
