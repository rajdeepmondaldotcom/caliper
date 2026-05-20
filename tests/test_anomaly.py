from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from caliper.anomaly import (
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
        model="claude-opus-4.7",
        service_tier="standard",
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
    events = [_event(session=f"s{i}", ts=base, input_tokens=100) for i in range(8)]
    events.append(_event(session="huge", ts=base, input_tokens=10_000_000, output_tokens=100_000))
    anomalies = detect_session_anomalies(events, _card())
    assert len(anomalies) >= 1
    assert anomalies[0].label == "huge"
    assert anomalies[0].z_score >= 3.0
    assert anomalies[0].impact_usd_exact > Decimal("0")


def test_detect_session_anomalies_with_constant_costs_returns_empty():
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    events = [
        _event(session=f"s{i}", ts=base, input_tokens=100, output_tokens=10) for i in range(8)
    ]
    assert detect_session_anomalies(events, _card()) == []


def _daily(label: str, cost_usd: float) -> Aggregate:
    totals = TokenTotals()
    costs = CostTotals(cost_usd=Decimal(str(cost_usd)))
    ts = dt.datetime(2026, 5, 12, 0, 0, tzinfo=dt.UTC)
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
    rows = [_daily(f"d{i}", 1.0) for i in range(10)]
    rows.append(_daily("spike", 50.0))
    anomalies = detect_daily_anomalies(rows)
    assert any(a.label == "spike" for a in anomalies)


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
