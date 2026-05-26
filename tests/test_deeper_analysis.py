"""WS3 deeper-analysis helpers: honest git-attribution coverage and the
cache-efficiency trend. Both are evidence-labelled and must never invent
precision on sparse input."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from caliper.attribution import git_attribution_coverage
from caliper.models import (
    Aggregate,
    CostTotals,
    ThreadMeta,
    TokenTotals,
    TurnFacts,
    Usage,
    UsageEvent,
)
from caliper.predict import cache_efficiency_trend
from caliper.pricing import RateCard


def _event(*, sha: str, model: str = "gpt-5.5", input_tokens: int = 10_000) -> UsageEvent:
    return UsageEvent(
        timestamp=dt.datetime(2026, 5, 12, 14, 0, tzinfo=dt.UTC),
        path=Path("/tmp/r.jsonl"),
        session_id="s1",
        usage=Usage(input_tokens=input_tokens, output_tokens=200, total_tokens=input_tokens + 200),
        model=model,
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(first_user_message="x", cwd="/p", git_sha=sha),
        turn_facts=TurnFacts(tool_use_count=0),
    )


def _daily(input_tokens: int, cached: int, day: int) -> Aggregate:
    return Aggregate(
        key=f"d{day}",
        label=f"2026-05-{day:02d}",
        totals=TokenTotals(input_tokens=input_tokens, cached_input_tokens=cached),
        costs=CostTotals(cost_usd=Decimal("1")),
        first_seen=dt.datetime(2026, 5, day, tzinfo=dt.UTC),
        last_seen=dt.datetime(2026, 5, day, tzinfo=dt.UTC),
    )


def test_git_attribution_coverage_reports_partial_when_some_events_lack_sha():
    card = RateCard.load(None, "model")
    events = [_event(sha="abc123")] * 2 + [_event(sha="")] * 6
    cov = git_attribution_coverage(events, card)
    assert cov["events_total"] == 8
    assert cov["events_with_sha"] == 2
    assert cov["sha_coverage"] == 0.25
    assert 0.0 < cov["cost_coverage"] < 1.0
    assert cov["evidence_status"] == "partial"


def test_git_attribution_coverage_is_exact_when_all_events_have_sha():
    card = RateCard.load(None, "model")
    cov = git_attribution_coverage([_event(sha="abc")] * 3, card)
    assert cov["sha_coverage"] == 1.0
    assert cov["evidence_status"] == "exact"


def test_git_attribution_coverage_handles_no_events():
    cov = git_attribution_coverage([], RateCard.load(None, "model"))
    assert cov["events_total"] == 0
    assert cov["cost_coverage"] == 0.0
    assert cov["evidence_status"] == "partial"


def test_cache_trend_flags_declining_reuse():
    # Cache hit ratio erodes 100% → 60% across the window.
    daily = [_daily(10_000, int(10_000 * r), d) for d, r in enumerate((1.0, 0.9, 0.8, 0.7, 0.6), 1)]
    trend = cache_efficiency_trend(daily)
    assert trend["direction"] == "declining"
    assert trend["slope_per_day"] < 0
    assert trend["evidence_status"] == "exact"
    assert trend["days_analyzed"] == 5


def test_cache_trend_flat_when_stable():
    daily = [_daily(10_000, 9_500, d) for d in range(1, 8)]
    trend = cache_efficiency_trend(daily)
    assert trend["direction"] == "flat"
    assert abs(trend["current_ratio"] - 0.95) < 1e-9


def test_cache_trend_under_sampled_is_partial_and_flat():
    daily = [_daily(10_000, 9_000, d) for d in range(1, 3)]  # 2 days < MIN_OLS_POINTS
    trend = cache_efficiency_trend(daily)
    assert trend["direction"] == "flat"
    assert trend["evidence_status"] == "partial"


def test_cache_trend_skips_zero_input_days():
    daily = [_daily(0, 0, 1), _daily(10_000, 9_000, 2), _daily(0, 0, 3)]
    trend = cache_efficiency_trend(daily)
    # Only one usable day; under-sampled but not a crash.
    assert trend["days_analyzed"] == 1
    assert trend["current_ratio"] == 0.9
