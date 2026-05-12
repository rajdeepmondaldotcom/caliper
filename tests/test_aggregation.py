"""Aggregation function numerics pinned against an in-memory LoadResult."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from codex_meter.aggregation import (
    aggregate_daily,
    aggregate_model_mode,
    aggregate_monthly,
    aggregate_projects,
    aggregate_sessions,
    aggregate_total,
    aggregate_weekly,
)
from codex_meter.config import build_options
from codex_meter.models import LoadResult, ThreadMeta, Usage, UsageEvent


def _event(
    timestamp: dt.datetime,
    *,
    input_tokens: int = 1000,
    cached_input_tokens: int = 500,
    output_tokens: int = 100,
    total_tokens: int = 1100,
    model: str = "gpt-5.5",
    service_tier: str = "standard",
    cwd: str = "/repo/a",
    session_id: str = "sess-a",
) -> UsageEvent:
    return UsageEvent(
        timestamp=timestamp,
        path=Path("/dev/null"),
        session_id=session_id,
        usage=Usage(
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_output_tokens=0,
            total_tokens=total_tokens,
        ),
        model=model,
        service_tier=service_tier,
        tier_source="logged",
        thread=ThreadMeta(cwd=cwd, model=model),
        plan_type="pro",
    )


def _options(tmp_path):
    return build_options(
        days=30,
        session_root=tmp_path / "missing-sessions",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
    )


def _result(events: list) -> LoadResult:
    return LoadResult(
        events=events,
        duplicates=0,
        tier_sources={"logged": len(events)},
        plan_types={"pro"},
        credit_samples=[],
        warnings=[],
    )


def test_aggregate_total_sums_tokens(tmp_path) -> None:
    now = dt.datetime.now(tz=dt.UTC)
    events = [_event(now), _event(now + dt.timedelta(minutes=5))]
    total = aggregate_total(_result(events), _options(tmp_path))
    assert total.totals.events == 2
    assert total.totals.input_tokens == 2000
    assert total.totals.cached_input_tokens == 1000
    assert total.totals.output_tokens == 200
    assert total.totals.total_tokens == 2200


def test_aggregate_daily_groups_by_date(tmp_path) -> None:
    base = dt.datetime(2026, 5, 10, 12, 0, tzinfo=dt.UTC)
    events = [
        _event(base),
        _event(base + dt.timedelta(hours=1)),
        _event(base + dt.timedelta(days=1)),
    ]
    rows = aggregate_daily(_result(events), _options(tmp_path))
    assert len(rows) == 2
    assert rows[0].totals.events == 2
    assert rows[1].totals.events == 1


def test_aggregate_weekly_groups_by_iso_week(tmp_path) -> None:
    base = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    events = [_event(base), _event(base + dt.timedelta(days=10))]
    rows = aggregate_weekly(_result(events), _options(tmp_path))
    assert len(rows) == 2
    assert all(row.key.startswith("2026-W") for row in rows)


def test_aggregate_monthly_groups_by_month(tmp_path) -> None:
    events = [
        _event(dt.datetime(2026, 4, 15, tzinfo=dt.UTC)),
        _event(dt.datetime(2026, 5, 3, tzinfo=dt.UTC)),
        _event(dt.datetime(2026, 5, 20, tzinfo=dt.UTC)),
    ]
    rows = aggregate_monthly(_result(events), _options(tmp_path))
    assert [row.key for row in rows] == ["2026-04", "2026-05"]
    assert rows[1].totals.events == 2


def test_aggregate_sessions_sorted_by_credits_desc(tmp_path) -> None:
    now = dt.datetime.now(tz=dt.UTC)
    events = [
        _event(now, session_id="sess-small", input_tokens=100, output_tokens=10),
        _event(now, session_id="sess-large", input_tokens=10000, output_tokens=1000),
    ]
    rows = aggregate_sessions(_result(events), _options(tmp_path))
    assert rows[0].key == "sess-large"
    assert rows[1].key == "sess-small"


def test_aggregate_projects_groups_by_cwd(tmp_path) -> None:
    now = dt.datetime.now(tz=dt.UTC)
    events = [_event(now, cwd="/repo/a"), _event(now, cwd="/repo/b"), _event(now, cwd="/repo/a")]
    rows = aggregate_projects(_result(events), _options(tmp_path))
    labels = [row.label for row in rows]
    assert set(labels) == {"/repo/a", "/repo/b"}
    a_row = next(row for row in rows if row.label == "/repo/a")
    assert a_row.totals.events == 2


def test_aggregate_model_mode_keys_combine_model_and_tier(tmp_path) -> None:
    now = dt.datetime.now(tz=dt.UTC)
    events = [
        _event(now, model="gpt-5.5", service_tier="standard"),
        _event(now, model="gpt-5.5", service_tier="fast"),
        _event(now, model="gpt-5.4", service_tier="standard"),
    ]
    rows = aggregate_model_mode(_result(events), _options(tmp_path))
    assert len(rows) == 3
    labels = {row.label for row in rows}
    assert "gpt-5.5 / standard" in labels
    assert "gpt-5.5 / fast" in labels
    assert "gpt-5.4 / standard" in labels
