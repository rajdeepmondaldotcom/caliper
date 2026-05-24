from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from caliper.anomaly import (
    detect_actionable_anomalies,
    detect_daily_anomalies,
    detect_model_anomalies,
    detect_project_daily_anomalies,
    detect_session_anomalies,
)
from caliper.models import (
    Aggregate,
    CostTotals,
    ThreadMeta,
    TokenTotals,
    TurnFacts,
    Usage,
    UsageEvent,
)
from caliper.pricing import RateCard


def _card() -> RateCard:
    return RateCard.load(None, "model")


def _event(
    *,
    session: str,
    ts: dt.datetime,
    input_tokens: int = 1_000,
    output_tokens: int = 100,
    cwd: str = "/tmp/p",
    model: str = "claude-opus-4.7",
    service_tier: str = "standard",
) -> UsageEvent:
    return UsageEvent(
        timestamp=ts,
        path=Path("/tmp/r.jsonl"),
        session_id=session,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        model=model,
        service_tier=service_tier,
        tier_source="logged",
        thread=ThreadMeta(cwd=cwd),
        turn_facts=TurnFacts(),
    )


def test_detect_session_anomalies_under_min_samples_returns_empty():
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    events = [_event(session=f"s{i}", ts=base) for i in range(3)]
    assert detect_session_anomalies(events, _card()) == []


def test_detect_session_anomalies_flags_spike():
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    events = [
        _event(session=f"s{i}", ts=base + dt.timedelta(days=i), input_tokens=100)
        for i in range(8)
    ]
    events.append(
        _event(
            session="huge",
            ts=base + dt.timedelta(days=9),
            input_tokens=10_000_000,
            output_tokens=100_000,
        )
    )
    anomalies = detect_session_anomalies(events, _card())
    assert len(anomalies) >= 1
    assert anomalies[0].label == "huge"
    assert anomalies[0].z_score >= 3.0
    assert anomalies[0].impact_usd_exact > Decimal("0")
    assert anomalies[0].baseline_sample_count == 8
    assert "prior sessions" in anomalies[0].comparison_scope


def test_detect_session_anomalies_ignores_broad_baseline_without_matching_cohort():
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    events = [
        _event(
            session=f"s{i}",
            ts=base + dt.timedelta(days=i),
            input_tokens=100,
            cwd=f"/tmp/project-{i}",
        )
        for i in range(8)
    ]
    events.append(
        _event(
            session="huge",
            ts=base + dt.timedelta(days=9),
            input_tokens=10_000_000,
            output_tokens=100_000,
            cwd="/tmp/rare-project",
            model="gpt-5.5",
        )
    )

    assert detect_session_anomalies(events, _card()) == []
    assert detect_actionable_anomalies(events, _card(), "UTC") == []


def test_detect_session_anomalies_with_constant_costs_returns_empty():
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    events = [
        _event(session=f"s{i}", ts=base, input_tokens=100, output_tokens=10) for i in range(8)
    ]
    assert detect_session_anomalies(events, _card()) == []


def _daily(label: str, cost_usd: float) -> Aggregate:
    totals = TokenTotals()
    costs = CostTotals(cost_usd=Decimal(str(cost_usd)))
    try:
        date = dt.date.fromisoformat(label)
    except ValueError:
        date = dt.date(2026, 5, 12)
    ts = dt.datetime.combine(date, dt.time(), tzinfo=dt.UTC)
    agg = Aggregate(
        key=label,
        label=label,
        totals=totals,
        costs=costs,
        first_seen=ts,
        last_seen=ts,
    )
    return agg


def test_detect_daily_anomalies_under_min_returns_empty():
    rows = [_daily(f"d{i}", 1.0) for i in range(3)]
    assert detect_daily_anomalies(rows) == []


def test_detect_daily_anomalies_flags_spike():
    rows = [_daily(f"2026-05-{i:02d}", 1.0) for i in range(1, 11)]
    rows.append(_daily("2026-05-11", 50.0))
    anomalies = detect_daily_anomalies(rows)
    assert any(a.label == "2026-05-11" for a in anomalies)


def test_detect_daily_anomalies_returns_empty_for_constant_series():
    rows = [_daily(f"d{i}", 1.0) for i in range(10)]
    assert detect_daily_anomalies(rows) == []


def test_detect_model_anomalies_flags_day_spike():
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    events = []
    for i in range(6):
        events.append(_event(session=f"s{i}", ts=base + dt.timedelta(days=i), input_tokens=1_000))
    events.append(
        _event(
            session="big",
            ts=base + dt.timedelta(days=20),
            input_tokens=10_000_000,
            output_tokens=100_000,
        )
    )
    anomalies = detect_model_anomalies(events, _card())
    assert any("claude-opus-4.7" in a.label for a in anomalies)


def test_detect_project_daily_anomalies_flags_project_local_spike():
    base = dt.datetime(2026, 5, 1, 10, 0, tzinfo=dt.UTC)
    events = [
        _event(session=f"s{i}", ts=base + dt.timedelta(days=i), input_tokens=1_000)
        for i in range(6)
    ]
    events.append(
        _event(
            session="big",
            ts=base + dt.timedelta(days=7),
            input_tokens=10_000_000,
            output_tokens=100_000,
        )
    )
    anomalies = detect_project_daily_anomalies(events, _card(), "UTC")
    assert any(a.kind == "project_day_spike" and "/tmp/p" in a.label for a in anomalies)


def test_detect_project_daily_anomalies_requires_project_history():
    base = dt.datetime(2026, 5, 1, 10, 0, tzinfo=dt.UTC)
    events = [
        _event(session=f"s{i}", ts=base + dt.timedelta(days=i), cwd="/tmp/sparse") for i in range(3)
    ]
    assert detect_project_daily_anomalies(events, _card(), "UTC") == []


# ---------------------------------------------------------------------------
# Conservative-detector regression tests — guard against the 354,210σ bug.
# ---------------------------------------------------------------------------


def test_detect_daily_anomalies_does_not_explode_on_sparse_data():
    """The old detector produced 354,210σ for a $300 spike against a sea
    of zero-cost days because median collapsed and the scale fallback
    became < $0.001. The new detector caps σ and floors the scale so
    sparse-series spikes register as a sane "≥20σ extreme" instead.
    """
    rows = [_daily(f"2026-05-{i:02d}", 0.0) for i in range(1, 29)]
    rows.append(_daily("2026-05-29", 307.87))
    rows.append(_daily("2026-05-30", 0.001))
    anomalies = detect_daily_anomalies(rows)
    assert len(anomalies) >= 1
    spike = next(a for a in anomalies if a.label == "2026-05-29")
    # The cap is 20.0; anything beyond is "extreme", not a real number.
    assert spike.z_score <= 20.0
    assert spike.baseline_scale >= 1.0  # $1 absolute floor


def test_detect_daily_anomalies_requires_minimum_dollar_impact():
    """A 4× spike worth $0.40 isn't worth interrupting the user."""
    rows = [_daily(f"2026-05-{i:02d}", 0.10) for i in range(1, 9)]
    rows.append(_daily("2026-05-09", 0.40))  # 4× but only $0.30 above baseline
    assert detect_daily_anomalies(rows) == []


def test_detect_daily_anomalies_requires_3x_fold_change():
    """A 2× spike on a regular day isn't a spike — it's normal drift."""
    rows = [_daily(f"2026-05-{i:02d}", 10.0) for i in range(1, 9)]
    rows.append(_daily("2026-05-09", 20.0))  # exactly 2× — below the 3× gate
    assert detect_daily_anomalies(rows) == []


def test_detect_daily_anomalies_caps_displayed_sigma():
    """Even a real 50× spike should report ≤ 20σ for display sanity."""
    rows = [_daily(f"2026-05-{i:02d}", 1.0) for i in range(1, 9)]
    rows.append(_daily("2026-05-09", 500.0))  # 500× the baseline
    anomalies = detect_daily_anomalies(rows)
    assert anomalies
    assert anomalies[0].z_score <= 20.0
    # Impact is still the real dollar delta, only σ is capped.
    assert anomalies[0].impact_usd_exact > Decimal("400")
