from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from caliper.models import (
    LoadResult,
    RateLimitSample,
    ThreadMeta,
    TurnFacts,
    Usage,
    UsageEvent,
)
from caliper.predict import (
    decompose_seasonality,
    forecast_per_model,
    forecast_rate_limits,
    linear_slope,
    safe_ratio,
    total_outlook,
)
from caliper.pricing import RateCard


def _card() -> RateCard:
    return RateCard.load(None, "model")


def _event(
    *,
    ts: dt.datetime,
    model: str = "claude-opus-4.7",
    input_tokens: int = 1_000,
    output_tokens: int = 500,
    total_tokens: int | None = None,
    session: str = "s1",
) -> UsageEvent:
    total = total_tokens if total_tokens is not None else input_tokens + output_tokens
    return UsageEvent(
        timestamp=ts,
        path=Path("/tmp/r.jsonl"),
        session_id=session,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
        ),
        model=model,
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(cwd="/tmp/p"),
        turn_facts=TurnFacts(),
    )


def test_linear_slope_under_min_points_returns_zero():
    assert linear_slope([(1, 10), (2, 20)]) == 0.0


def test_linear_slope_perfect_line():
    pts = [(1, 10), (2, 20), (3, 30), (4, 40), (5, 50)]
    assert linear_slope(pts) == pytest.approx(10.0)


def test_linear_slope_zero_variance_returns_zero():
    assert linear_slope([(1, 5), (1, 5), (1, 5), (1, 5)]) == 0.0


def test_forecast_per_model_empty():
    assert forecast_per_model([], _card(), "UTC") == []


def test_forecast_per_model_handles_multiple_days_and_models():
    base = dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.UTC)
    events = []
    for offset in range(7):
        events.append(
            _event(
                ts=base + dt.timedelta(days=offset),
                model="claude-opus-4.7",
                input_tokens=1_000 * (offset + 1),
            )
        )
        events.append(
            _event(
                ts=base + dt.timedelta(days=offset),
                model="gpt-5.4-mini",
                input_tokens=500,
            )
        )
    cards = forecast_per_model(events, _card(), "UTC")
    by_model = {c.model: c for c in cards}
    assert "claude-opus-4.7" in by_model
    assert "gpt-5.4-mini" in by_model
    assert by_model["claude-opus-4.7"].trend_slope_tokens_per_day > 0
    assert by_model["claude-opus-4.7"].growing is True
    assert by_model["gpt-5.4-mini"].growing is False
    shares = sum(c.projected_share_30d for c in cards)
    assert shares == pytest.approx(1.0, abs=1e-6)


def test_decompose_seasonality_empty_events_returns_zero_profile():
    profile = decompose_seasonality([], _card(), "UTC")
    assert profile.off_peak_share == 0.0
    assert sum(profile.by_hour_cost_usd) == 0.0


def test_decompose_seasonality_marks_peak_hour():
    events = [
        _event(ts=dt.datetime(2026, 5, 12, 9, 0, tzinfo=dt.UTC), input_tokens=10_000),
        _event(ts=dt.datetime(2026, 5, 12, 9, 30, tzinfo=dt.UTC), input_tokens=20_000),
        _event(ts=dt.datetime(2026, 5, 12, 22, 0, tzinfo=dt.UTC), input_tokens=200),
    ]
    profile = decompose_seasonality(events, _card(), "UTC")
    assert profile.peak_hour == 9
    assert profile.timezone == "UTC"


def _sample(ts: dt.datetime, primary: float, secondary: float = 50.0) -> RateLimitSample:
    return RateLimitSample(
        timestamp=ts,
        path=Path("/tmp/r.jsonl"),
        session_id="s1",
        plan_type="pro",
        limit_id="codex",
        limit_name="codex",
        primary_used_percent=primary,
        primary_window_minutes=300,
        primary_resets_at=int(ts.timestamp() + 3600),
        secondary_used_percent=secondary,
        secondary_window_minutes=10080,
        secondary_resets_at=int(ts.timestamp() + 86400),
    )


def test_forecast_rate_limits_empty_returns_empty():
    assert forecast_rate_limits([]) == []


def test_forecast_rate_limits_high_confidence_with_burn():
    base = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    samples = [_sample(base + dt.timedelta(hours=i), 10.0 + i * 5) for i in range(6)]
    forecasts = forecast_rate_limits(samples)
    primary = next(f for f in forecasts if f.window == "primary")
    assert primary.confidence == "high"
    assert primary.eta_to_100_hours is not None and primary.eta_to_100_hours > 0
    assert primary.eta_low_hours is not None
    assert primary.eta_high_hours is not None
    assert primary.eta_low_hours <= primary.eta_to_100_hours <= primary.eta_high_hours


def test_forecast_rate_limits_below_100_when_already_full():
    base = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    samples = [_sample(base + dt.timedelta(minutes=10 * i), 100.0) for i in range(5)]
    forecasts = forecast_rate_limits(samples)
    primary = next(f for f in forecasts if f.window == "primary")
    assert primary.eta_to_100_hours is None


def test_total_outlook_returns_both_horizons():
    out = total_outlook([10.0] * 5)
    assert set(out) == {"30d", "90d"}
    assert out["30d"].linear_total == pytest.approx(300.0)
    assert out["90d"].linear_total == pytest.approx(900.0)


@pytest.mark.parametrize(
    "num,den,expected",
    [
        (10, 0, 0.0),
        (10, 2, 5.0),
        (float("nan"), 1, 0.0),
        (float("inf"), 1, 0.0),
    ],
)
def test_safe_ratio_defensive(num, den, expected):
    assert safe_ratio(num, den) == expected


def test_forecast_per_model_short_history_no_growth():
    base = dt.datetime(2026, 5, 12, 0, 0, tzinfo=dt.UTC)
    events = [_event(ts=base, model="gpt-5.5", input_tokens=1_000)]
    cards = forecast_per_model(events, _card(), "UTC")
    assert len(cards) == 1
    assert cards[0].growing is False
    assert cards[0].trend_slope_tokens_per_day == 0.0


def _load_result(events: list[UsageEvent]) -> LoadResult:
    return LoadResult(
        events=events,
        duplicates=0,
        tier_sources={"logged": len(events)},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )


def test_forecast_project_burn_skips_short_history(tmp_path):
    from caliper.config import build_options
    from caliper.models import Aggregate, CostTotals, TokenTotals
    from caliper.predict import forecast_project_burn

    options = build_options(
        days=7,
        until="2026-05-20T00:00:00Z",
        session_root=tmp_path,
        state_db=tmp_path / "s.sqlite",
        codex_config=tmp_path / "c.toml",
    )
    short = Aggregate(
        key="/a",
        label="/a",
        totals=TokenTotals(),
        costs=CostTotals(cost_usd=Decimal("1")),
        first_seen=dt.datetime(2026, 5, 19, tzinfo=dt.UTC),
        last_seen=dt.datetime(2026, 5, 19, tzinfo=dt.UTC),
    )
    assert forecast_project_burn([short], options) == {}


def test_forecast_project_burn_uses_daily_factory(tmp_path):
    from caliper.config import build_options
    from caliper.models import Aggregate, CostTotals, TokenTotals
    from caliper.predict import forecast_project_burn

    options = build_options(
        days=10,
        until="2026-05-20T00:00:00Z",
        session_root=tmp_path,
        state_db=tmp_path / "s.sqlite",
        codex_config=tmp_path / "c.toml",
    )
    rich = Aggregate(
        key="/a",
        label="/a",
        totals=TokenTotals(),
        costs=CostTotals(cost_usd=Decimal("50")),
        first_seen=dt.datetime(2026, 5, 10, tzinfo=dt.UTC),
        last_seen=dt.datetime(2026, 5, 19, tzinfo=dt.UTC),
    )
    forecasts = forecast_project_burn(
        [rich],
        options,
        daily_factory=lambda _row: [5.0, 4.0, 6.0, 5.5, 5.0],
    )
    assert "/a" in forecasts


def test_per_project_daily_cost_groups_by_project(tmp_path):
    from caliper.config import build_options
    from caliper.predict import per_project_daily_cost

    options = build_options(
        days=2,
        until="2026-05-14T00:00:00Z",
        session_root=tmp_path,
        state_db=tmp_path / "s.sqlite",
        codex_config=tmp_path / "c.toml",
    )
    base = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    events = [
        _event(ts=base, session="a", input_tokens=2_000),
        _event(ts=base + dt.timedelta(days=1), session="b", input_tokens=4_000),
    ]
    result = _load_result(events)
    out = per_project_daily_cost(result, _card(), options)
    assert "/tmp/p" in out
    assert len(out["/tmp/p"]) >= 1


def test_forecast_per_model_short_window_returns_no_growing():
    base = dt.datetime(2026, 5, 12, tzinfo=dt.UTC)
    events = [_event(ts=base + dt.timedelta(days=i), input_tokens=1_000) for i in range(2)]
    cards = forecast_per_model(events, _card(), "UTC")
    assert all(not card.growing for card in cards)


def test_decompose_seasonality_off_peak_share_within_bounds():
    base = dt.datetime(2026, 5, 12, 9, 0, tzinfo=dt.UTC)
    events = [
        _event(ts=base + dt.timedelta(hours=h), input_tokens=1_000 * (h + 1)) for h in range(12)
    ]
    profile = decompose_seasonality(events, _card(), "UTC")
    assert 0.0 <= profile.off_peak_share <= 1.0
