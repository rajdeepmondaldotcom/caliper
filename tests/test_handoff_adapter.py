"""Unit tests for caliper.dashboards.adapter."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from caliper.config import build_options
from caliper.dashboards.adapter import (
    _SHAPE_NAME_MAP,
    _build_banner,
    _build_evidence,
    _build_model_rows,
    _build_project_rows,
    _build_rate_limit_pressure,
    _build_session_shape,
    build_handoff_dashboard,
    tool_category,
)
from caliper.dashboards.data_models import Banner
from caliper.models import (
    VENDOR_CLAUDE_CODE,
    VENDOR_OPENAI_CODEX,
    Aggregate,
    CostTotals,
    LoadResult,
    RateLimitSample,
    ThreadMeta,
    TokenTotals,
    Usage,
    UsageEvent,
)
from caliper.parser import load_usage

# ----- Tiny fixture infrastructure -----


def _write_session(tmp_path, rows, slug: str = "-tmp-project"):
    projects = tmp_path / "claude" / "projects" / slug
    projects.mkdir(parents=True)
    (projects / "session.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def _row(
    *,
    i: int,
    cwd: str = "/tmp/project-alpha",
    tools=("Read", "Edit"),
    timestamp: str | None = None,
):
    return {
        "type": "assistant",
        "sessionId": "s1",
        "uuid": f"e-{i}",
        "parentUuid": f"p-{i}",
        "timestamp": timestamp or f"2026-05-12T10:{i:02d}:00.000Z",
        "cwd": cwd,
        "requestId": f"r-{i}",
        "message": {
            "id": f"m-{i}",
            "role": "assistant",
            "model": "claude-sonnet-4-6-20260501",
            "content": [{"type": "tool_use", "name": name, "input": {}} for name in tools],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
    }


def _options(tmp_path):
    return build_options(
        since="2026-05-12",
        until="2026-05-13",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )


def _aggregate(
    label: str,
    *,
    cost: float,
    events: int,
    tokens: int,
    model: str = "claude-sonnet-4-6",
    model_vendor: str = "anthropic",
    tier: str = "standard",
    sessions: int = 1,
) -> Aggregate:
    agg = Aggregate(key=label, label=label)
    agg.costs = CostTotals(cost_usd=cost)
    agg.totals = TokenTotals(events=events, input_tokens=tokens, total_tokens=tokens)
    agg.models.add(model)
    agg.model_vendors.add(model_vendor)
    agg.service_tiers.add(tier)
    agg.session_ids = {f"s{i}" for i in range(sessions)}
    return agg


def _empty_load_result() -> LoadResult:
    return LoadResult(
        events=[],
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )


# ----- tool_category -----


def test_tool_category_classifies_known_tools() -> None:
    assert tool_category("Read") == "explore"
    assert tool_category("Grep") == "explore"
    assert tool_category("Edit") == "execute"
    assert tool_category("Write") == "execute"
    assert tool_category("Bash") == "diagnose"
    assert tool_category("UnknownTool") == "mixed"


def test_shape_name_map_is_total_for_categories() -> None:
    """Every category used by classify_session must map to a SessionShapeName."""
    from caliper.analysis.session_shape import (
        CATEGORY_DIAGNOSTIC,
        CATEGORY_EXECUTION,
        CATEGORY_EXPLORATION,
        CATEGORY_MIXED,
        CATEGORY_NONE,
    )

    assert _SHAPE_NAME_MAP[CATEGORY_EXPLORATION] == "exploration"
    assert _SHAPE_NAME_MAP[CATEGORY_EXECUTION] == "execution"
    assert _SHAPE_NAME_MAP[CATEGORY_DIAGNOSTIC] == "diagnostic"
    assert _SHAPE_NAME_MAP[CATEGORY_MIXED] == "mixed"
    assert _SHAPE_NAME_MAP[CATEGORY_NONE] == "no-tools"


# ----- _build_session_shape -----


def test_build_session_shape_assigns_categories(monkeypatch, tmp_path) -> None:
    _write_session(tmp_path, [_row(i=i) for i in range(1, 4)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    result = load_usage(_options(tmp_path))

    from caliper.analysis.session_shape import compute_session_shape

    report = compute_session_shape(result)
    shape = _build_session_shape(report)

    assert shape.total_sessions == 1
    # Top tools tagged with category
    names = {t.name: t.category for t in shape.top_tools}
    assert names.get("Read") == "explore"
    assert names.get("Edit") == "execute"
    # Categories share sums to ~1
    assert abs(sum(c.share for c in shape.categories) - 1.0) < 1e-9


# ----- build_handoff_dashboard (end-to-end) -----


def test_build_handoff_dashboard_decimal_to_float(monkeypatch, tmp_path) -> None:
    _write_session(tmp_path, [_row(i=i) for i in range(1, 4)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)
    d = build_handoff_dashboard(result, options, with_deltas=False)
    assert isinstance(d.totals.cost_usd, float)
    assert isinstance(d.totals.cache_savings_usd, float)
    assert d.totals.events > 0
    # Sparklines line up with daily series length.
    assert len(d.totals.daily_cost_sparkline) == len(d.daily)
    assert len(d.totals.daily_token_sparkline) == len(d.daily)
    assert len(d.totals.daily_session_sparkline) == len(d.daily)
    assert d.command_center
    assert d.top_sessions
    assert d.top_sessions[0].label == "10:01 am, Tuesday 12 May 2026"
    assert "s1" not in d.top_sessions[0].label
    assert d.usage_mix
    assert d.rate_limit_pressure is not None
    assert d.quality_score is not None
    assert {row.dimension for row in d.usage_mix} >= {"vendor", "model/tier", "tier", "source"}


def test_usage_mix_keeps_codex_fast_reasoning_tiers_costed(tmp_path) -> None:
    def event(*, service_tier: str, reasoning_effort: str = "") -> UsageEvent:
        return UsageEvent(
            timestamp=dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC),
            path=tmp_path / "session.jsonl",
            session_id=f"codex-{service_tier}-{reasoning_effort or 'default'}",
            usage=Usage(
                input_tokens=1000, cached_input_tokens=0, output_tokens=100, total_tokens=1100
            ),
            model="gpt-5.5",
            service_tier=service_tier,
            tier_source="logged",
            thread=ThreadMeta(
                cwd="/tmp/project-alpha",
                model="gpt-5.5",
                source="cli",
                reasoning_effort=reasoning_effort,
            ),
            vendor=VENDOR_OPENAI_CODEX,
        )

    options = build_options(
        since="2026-05-12",
        until="2026-05-13",
        timezone="UTC",
        session_root=tmp_path / "missing-sessions",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_OPENAI_CODEX],
        no_parse_cache=True,
    )
    result = LoadResult(
        events=[
            event(service_tier="standard"),
            event(service_tier="fast", reasoning_effort="x-high"),
        ],
        duplicates=0,
        tier_sources={"logged": 2},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )

    d = build_handoff_dashboard(result, options, with_deltas=False)
    model_tiers = {row.label: row for row in d.usage_mix if row.dimension == "model/tier"}

    assert "gpt-5.5 · standard" in model_tiers
    assert "gpt-5.5 · fast · xhigh" in model_tiers
    assert model_tiers["gpt-5.5 · fast · xhigh"].cost_usd == pytest.approx(
        model_tiers["gpt-5.5 · standard"].cost_usd * 2.5
    )


def test_build_handoff_dashboard_zero_fills_daily(monkeypatch, tmp_path) -> None:
    """Daily points are continuous: every day in the window appears even
    if no events landed on it (cost_usd=0, events=0, shape='no-tools')."""
    _write_session(tmp_path, [_row(i=1)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)
    d = build_handoff_dashboard(result, options, with_deltas=False)
    # Days are continuous and the first one matches the event timestamp.
    days = [p.day for p in d.daily]
    assert days == sorted(days)
    assert days[0] == "2026-05-12"
    event_day = next(p for p in d.daily if p.day == "2026-05-12")
    assert event_day.events == 1
    # Days with no events have shape "no-tools" and cost 0.
    for p in d.daily:
        if p.day != "2026-05-12":
            assert p.cost_usd == 0.0
            assert p.events == 0
            assert p.shape == "no-tools"


def test_build_handoff_dashboard_no_deltas_when_disabled(monkeypatch, tmp_path) -> None:
    _write_session(tmp_path, [_row(i=1)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)
    d = build_handoff_dashboard(result, options, with_deltas=False)
    assert d.totals.delta_cost_pct is None
    assert d.totals.delta_tokens_pct is None


def test_build_model_rows_are_sorted_by_cost_then_usage() -> None:
    rows = _build_model_rows(
        [
            _aggregate("mid-events", cost=2.0, events=20, tokens=300, model="model-b"),
            _aggregate("top", cost=4.0, events=1, tokens=100, model="model-a"),
            _aggregate("mid-tokens", cost=2.0, events=5, tokens=900, model="model-c"),
        ]
    )

    assert [row.model for row in rows] == ["model-a", "model-c", "model-b"]


def test_build_project_rows_are_sorted_by_cost_then_activity(tmp_path) -> None:
    options = _options(tmp_path)
    rows = _build_project_rows(
        [
            _aggregate("/tmp/project-b", cost=3.0, events=10, tokens=100, sessions=1),
            _aggregate("/tmp/project-a", cost=5.0, events=1, tokens=100, sessions=1),
            _aggregate("/tmp/project-c", cost=3.0, events=12, tokens=100, sessions=1),
        ],
        _empty_load_result(),
        show_paths=True,
        options=options,
        daily_by_project={},
    )

    assert [row.name for row in rows] == ["project-a", "project-c", "project-b"]


def test_build_handoff_dashboard_adds_rolling_usage_windows(monkeypatch, tmp_path) -> None:
    rows = [
        _row(i=1, timestamp="2026-05-12T10:01:00.000Z"),
        _row(i=2, timestamp="2026-04-20T10:02:00.000Z"),
    ]
    _write_session(tmp_path, rows)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    selected_options = _options(tmp_path)
    rolling_options = build_options(
        since="2026-02-12",
        until="2026-05-13",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )
    selected = load_usage(selected_options)
    rolling = load_usage(rolling_options)

    d = build_handoff_dashboard(
        selected,
        selected_options,
        with_deltas=False,
        rolling_result=rolling,
        rolling_options=rolling_options,
        budget_config={},
    )

    assert d.totals.events == 1
    by_label = {window.label: window for window in d.usage_windows}
    assert list(by_label) == ["Last 7 days", "Last 30 days", "Last 90 days"]
    assert by_label["Last 7 days"].events == 1
    assert by_label["Last 30 days"].events == 2
    assert by_label["Last 90 days"].events == 2


def test_build_handoff_dashboard_adds_project_tracking_and_anomalies(monkeypatch, tmp_path) -> None:
    rows = []
    for offset in range(7):
        row = _row(
            i=offset + 1,
            cwd="/tmp/project-alpha",
            timestamp=f"2026-05-{10 + offset:02d}T10:00:00.000Z",
        )
        row["sessionId"] = f"s{offset + 1}"
        row["message"]["usage"]["input_tokens"] = 100
        rows.append(row)
    spike = _row(
        i=20,
        cwd="/tmp/project-alpha",
        timestamp="2026-05-17T10:00:00.000Z",
    )
    spike["sessionId"] = "huge"
    spike["message"]["usage"]["input_tokens"] = 10_000_000
    rows.append(spike)
    _write_session(tmp_path, rows)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = build_options(
        since="2026-05-10",
        until="2026-05-18",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )
    result = load_usage(options)

    d = build_handoff_dashboard(result, options, with_deltas=False)

    project = next(row for row in d.by_project if row.name == "project-alpha")
    assert project.active_days == 8
    assert project.daily_mean_cost_usd > 0
    assert project.projected_30d_cost_usd > 0
    assert len(project.daily_cost_sparkline) == (options.end.date() - options.start.date()).days
    assert any(row.kind == "Project-day spike" for row in d.anomalies)
    assert any(row.kind == "Session spike" for row in d.anomalies)
    session_spike = next(row for row in d.anomalies if row.kind == "Session spike")
    assert "huge" not in session_spike.label
    assert "2026" in session_spike.label


def test_build_handoff_dashboard_rolling_windows_are_deduped(monkeypatch, tmp_path) -> None:
    duplicate = _row(i=1)
    _write_session(tmp_path, [duplicate, duplicate])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)

    d = build_handoff_dashboard(result, options, with_deltas=False, budget_config={})

    assert result.duplicates == 1
    assert d.usage_windows[0].events == 1
    dedupe = next(card for card in d.impact_cards if card.label == "Dedupe")
    assert dedupe.value == "1 skipped"


def test_build_handoff_dashboard_impact_cards_include_budget_states(monkeypatch, tmp_path) -> None:
    _write_session(tmp_path, [_row(i=1)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)

    no_budget = build_handoff_dashboard(result, options, with_deltas=False, budget_config={})
    assert next(card for card in no_budget.impact_cards if card.label == "Budget risk").value == (
        "No budgets"
    )

    with_budget = build_handoff_dashboard(
        result,
        options,
        with_deltas=False,
        budget_config={"budgets": {"monthly_tokens": 10}},
    )
    budget = next(card for card in with_budget.impact_cards if card.label == "Budget risk")
    assert budget.tone == "critical"
    assert budget.value.endswith("%")


def test_build_handoff_dashboard_severity_mapping(monkeypatch, tmp_path) -> None:
    """`fail` severity from internal insights maps to handoff `critical`."""
    _write_session(tmp_path, [_row(i=i) for i in range(1, 5)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)
    d = build_handoff_dashboard(result, options, with_deltas=False)
    for ins in d.insights:
        assert ins.severity in {"info", "warn", "critical"}


def test_build_rate_limit_pressure_scores_peak_and_reached(tmp_path) -> None:
    result = LoadResult(
        events=[],
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[
            RateLimitSample(
                timestamp=dt.datetime(2026, 5, 12, 10, tzinfo=dt.UTC),
                path=tmp_path / "a.jsonl",
                session_id="s1",
                plan_type="max",
                limit_name="5-hour usage",
                primary_used_percent=81.0,
                secondary_used_percent=42.0,
            ),
            RateLimitSample(
                timestamp=dt.datetime(2026, 5, 12, 11, tzinfo=dt.UTC),
                path=tmp_path / "b.jsonl",
                session_id="s2",
                plan_type="max",
                limit_name="5-hour usage",
                primary_used_percent=97.0,
                secondary_used_percent=50.0,
                rate_limit_reached_type="primary",
            ),
        ],
        warnings=[],
    )

    pressure = _build_rate_limit_pressure(result)

    assert pressure.tone == "critical"
    assert pressure.peak_primary_pct == 0.97
    assert pressure.reached_count == 1
    assert pressure.latest_limit_name == "5-hour usage"


# ----- _build_evidence -----


def test_build_evidence_returns_at_least_one_dimension(monkeypatch, tmp_path) -> None:
    _write_session(tmp_path, [_row(i=1)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)
    from caliper.aggregation import aggregate_total

    total = aggregate_total(result, options)
    rows = _build_evidence(result, total)
    assert len(rows) >= 1
    for row in rows:
        assert row.status in {"exact", "estimated", "partial", "unsupported"}


# ----- _build_banner -----


def test_build_banner_returns_critical_for_very_stale_pricing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("caliper.dashboards.adapter.rate_card_age_days", lambda: 95)
    _write_session(tmp_path, [_row(i=1)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)
    banner = _build_banner(result, options)
    assert isinstance(banner, Banner)
    assert banner.kind == "crit"
    assert banner.label == "STALE"


def test_build_banner_returns_warn_for_partial_vendors(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("caliper.dashboards.adapter.rate_card_age_days", lambda: 5)
    _write_session(tmp_path, [_row(i=1)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)
    banner = _build_banner(result, options)
    assert isinstance(banner, Banner)
    assert banner.kind == "warn"
    assert banner.label == "PARTIAL"


def test_build_banner_returns_none_when_healthy(monkeypatch, tmp_path) -> None:
    """Synthesize multi-vendor coverage; expect no banner when pricing is fresh."""
    monkeypatch.setattr("caliper.dashboards.adapter.rate_card_age_days", lambda: 5)
    # Write a Claude Code event + synthesize a second vendor's event in-memory
    # by patching LoadResult on the fly. Simpler: skip this case by relying on
    # the boundary check — single vendor + fresh pricing already yields warn.
    # Instead: when both fresh pricing and >=2 vendors, banner is None.
    _write_session(tmp_path, [_row(i=1)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)

    # Manually fabricate "two vendors" by tagging one event with a different
    # vendor. UsageEvent is frozen; replace via dataclasses.replace.
    import dataclasses

    from caliper.models import VENDOR_OPENAI_CODEX

    second_event = dataclasses.replace(result.events[0], vendor=VENDOR_OPENAI_CODEX)
    result_two_vendors = dataclasses.replace(result, events=[*result.events, second_event])
    banner = _build_banner(result_two_vendors, options)
    assert banner is None


# ----- _build_project_rows: basename collision -----


def test_project_basename_collision_keeps_tool_lists_distinct(monkeypatch, tmp_path) -> None:
    """Two projects sharing a basename must keep distinct top-tool lists."""
    # Project A: /work/svc-a/api — exclusively Read
    rows_a = [
        {
            **_row(i=i, cwd="/work/svc-a/api", tools=("Read",)),
            "sessionId": "sa",
            "uuid": f"a-{i}",
            "requestId": f"ra-{i}",
            "message": {
                **_row(i=i, cwd="/work/svc-a/api").get("message", {}),
                "id": f"ma-{i}",
                "content": [{"type": "tool_use", "name": "Read", "input": {}}],
            },
        }
        for i in range(1, 4)
    ]
    # Project B: /work/svc-b/api — exclusively Bash (SAME basename)
    rows_b = [
        {
            **_row(i=i, cwd="/work/svc-b/api", tools=("Bash",)),
            "sessionId": "sb",
            "uuid": f"b-{i}",
            "requestId": f"rb-{i}",
            "message": {
                **_row(i=i, cwd="/work/svc-b/api").get("message", {}),
                "id": f"mb-{i}",
                "content": [{"type": "tool_use", "name": "Bash", "input": {}}],
            },
        }
        for i in range(1, 4)
    ]
    _write_session(tmp_path, rows_a, slug="-a")
    _write_session(tmp_path, rows_b, slug="-b")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    options = options.__class__(**{**options.__dict__, "show_paths": True})
    result = load_usage(options)
    d = build_handoff_dashboard(result, options, with_deltas=False)

    # Both projects have the same basename "api" — distinguish by path.
    rows_by_path = {row.path: row for row in d.by_project}
    assert "/work/svc-a/api" in rows_by_path
    assert "/work/svc-b/api" in rows_by_path
    a = rows_by_path["/work/svc-a/api"]
    b = rows_by_path["/work/svc-b/api"]
    a_tool_names = {t.name for t in a.top_tools}
    b_tool_names = {t.name for t in b.top_tools}
    assert "Read" in a_tool_names
    assert "Bash" not in a_tool_names
    assert "Bash" in b_tool_names
    assert "Read" not in b_tool_names


# ----- _daily_cache_sparkline: actual per-day rates -----


def test_daily_cache_sparkline_varies_per_day(monkeypatch, tmp_path) -> None:
    """Sparkline should reflect actual per-day cache mix, not the window-wide average."""
    high_cache_day = {
        "type": "assistant",
        "sessionId": "high",
        "uuid": "h-1",
        "timestamp": "2026-05-12T10:00:00.000Z",
        "cwd": "/tmp/p",
        "requestId": "rh-1",
        "message": {
            "id": "mh-1",
            "role": "assistant",
            "model": "claude-sonnet-4-6-20260501",
            "content": [{"type": "tool_use", "name": "Read", "input": {}}],
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 900,
                "output_tokens": 20,
            },
        },
    }
    low_cache_day = {
        "type": "assistant",
        "sessionId": "low",
        "uuid": "l-1",
        "timestamp": "2026-05-13T10:00:00.000Z",
        "cwd": "/tmp/p",
        "requestId": "rl-1",
        "message": {
            "id": "ml-1",
            "role": "assistant",
            "model": "claude-sonnet-4-6-20260501",
            "content": [{"type": "tool_use", "name": "Read", "input": {}}],
            "usage": {"input_tokens": 1000, "output_tokens": 20},
        },
    }
    _write_session(tmp_path, [high_cache_day, low_cache_day])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        since="2026-05-12",
        until="2026-05-14",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )
    result = load_usage(options)
    d = build_handoff_dashboard(result, options, with_deltas=False)
    spark = d.totals.daily_cache_sparkline
    # Day with 900 cached / 1000 input → 0.9; day with 0 cached / 1000 input → 0.
    by_day = dict(zip([p.day for p in d.daily], spark, strict=True))
    assert by_day["2026-05-12"] > 0.5  # high-cache day
    assert by_day["2026-05-13"] < 0.5  # low-cache day
    assert abs(by_day["2026-05-12"] - by_day["2026-05-13"]) > 0.3  # not flat
