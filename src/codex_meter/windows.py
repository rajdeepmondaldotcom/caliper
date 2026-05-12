"""Rate-limit window math. Pure functions, no I/O."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from codex_meter.models import RateLimitSample

BURN_RATE_LOOKBACK_HOURS = 6
MIN_BURN_RATE_SAMPLES = 3


@dataclass(frozen=True)
class WindowState:
    """Decoded state of a single rate-limit window at a moment in time."""

    window: str  # "primary" or "secondary"
    used_percent: float | None
    window_minutes: int | None
    reset_at: dt.datetime | None
    seconds_remaining: int | None
    burn_rate_per_hour: float | None  # percent points per hour
    eta_to_100: dt.datetime | None
    samples: int


def _coerce_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _epoch_to_datetime(value: object) -> dt.datetime | None:
    seconds = _coerce_int(value)
    if seconds is None:
        return None
    try:
        return dt.datetime.fromtimestamp(seconds, tz=dt.UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _percent(sample: RateLimitSample, which: str) -> float | None:
    return _coerce_float(getattr(sample, f"{which}_used_percent", None))


def _window_minutes(sample: RateLimitSample, which: str) -> int | None:
    return _coerce_int(getattr(sample, f"{which}_window_minutes", None))


def _reset_at(sample: RateLimitSample, which: str) -> dt.datetime | None:
    return _epoch_to_datetime(getattr(sample, f"{which}_resets_at", None))


def compute_window_state(
    samples: list[RateLimitSample], now: dt.datetime, which: str
) -> WindowState:
    """Compute a WindowState from raw RateLimitSamples. `which` is 'primary' or 'secondary'."""
    if which not in {"primary", "secondary"}:
        raise ValueError(f"window must be 'primary' or 'secondary', got {which!r}")
    if not samples:
        return WindowState(
            window=which,
            used_percent=None,
            window_minutes=None,
            reset_at=None,
            seconds_remaining=None,
            burn_rate_per_hour=None,
            eta_to_100=None,
            samples=0,
        )

    ordered = sorted(samples, key=lambda sample: sample.timestamp)
    latest = ordered[-1]
    used = _percent(latest, which)
    window_minutes = _window_minutes(latest, which)
    reset_at = _reset_at(latest, which)

    seconds_remaining: int | None = None
    if reset_at is not None:
        seconds_remaining = max(0, int((reset_at - now).total_seconds()))

    burn_rate = _compute_burn_rate(ordered, latest, which)
    eta_to_100 = _project_to_full(used, burn_rate, now)

    return WindowState(
        window=which,
        used_percent=used,
        window_minutes=window_minutes,
        reset_at=reset_at,
        seconds_remaining=seconds_remaining,
        burn_rate_per_hour=burn_rate,
        eta_to_100=eta_to_100,
        samples=len(ordered),
    )


def _compute_burn_rate(
    ordered: list[RateLimitSample], latest: RateLimitSample, which: str
) -> float | None:
    """Burn rate in percent-points per hour, derived from samples within the lookback window."""
    cutoff = latest.timestamp - dt.timedelta(hours=BURN_RATE_LOOKBACK_HOURS)
    recent = [sample for sample in ordered if sample.timestamp >= cutoff]
    if len(recent) < MIN_BURN_RATE_SAMPLES:
        return None
    first = recent[0]
    first_pct = _percent(first, which)
    last_pct = _percent(latest, which)
    if first_pct is None or last_pct is None:
        return None
    elapsed_hours = (latest.timestamp - first.timestamp).total_seconds() / 3600.0
    if elapsed_hours <= 0:
        return None
    return (last_pct - first_pct) / elapsed_hours


def _project_to_full(
    used: float | None, burn_rate: float | None, now: dt.datetime
) -> dt.datetime | None:
    if used is None or burn_rate is None or burn_rate <= 0 or used >= 100:
        return None
    hours_to_full = (100.0 - used) / burn_rate
    return now + dt.timedelta(hours=hours_to_full)


def format_seconds_remaining(seconds: int | None) -> str:
    """Render seconds as `Xh YYm ZZs`, `Ym Ss`, or `—`."""
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def format_burn_rate(rate: float | None) -> str:
    if rate is None:
        return "—"
    sign = "+" if rate >= 0 else ""
    return f"{sign}{rate:.2f}%/h"
