"""Unit tests for caliper.dashboards.adapter."""

from __future__ import annotations

import datetime as dt
import json

from caliper.config import build_options
from caliper.dashboards.adapter import (
    _SHAPE_NAME_MAP,
    _build_banner,
    _build_evidence,
    _build_model_rows,
    _build_project_rows,
    _build_rate_limit_pressure,
    _build_rate_limit_pressures_by_source,
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
    TokenTotals,
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
    assert d.top_sessions
    assert d.top_sessions[0].label == "10:01 am, Tuesday 12 May 2026"
    assert "s1" not in d.top_sessions[0].label
    assert d.rate_limit_pressure is not None
    assert d.quality_score is not None


def test_build_handoff_dashboard_reuses_expensive_inputs_and_reports_progress(
    monkeypatch,
    tmp_path,
) -> None:
    _write_session(tmp_path, [_row(i=i) for i in range(1, 4)])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)
    calls = {"audit": 0, "agents": 0, "skills": 0}

    def fake_run_audit(*_args, **_kwargs):
        calls["audit"] += 1
        return []

    def fake_agents(*_args, **_kwargs):
        calls["agents"] += 1
        return []

    def fake_skills(*_args, **_kwargs):
        calls["skills"] += 1
        return []

    class RecordingProgress:
        def __init__(self) -> None:
            self.details: list[str] = []

        def stage_advance(self, n: int = 1, detail: str | None = None) -> None:
            del n
            if detail:
                self.details.append(detail)

    monkeypatch.setattr("caliper.dashboards.adapter.run_audit", fake_run_audit)
    monkeypatch.setattr("caliper.dashboards.adapter.build_agent_attributions", fake_agents)
    monkeypatch.setattr("caliper.dashboards.adapter.build_skill_attributions", fake_skills)

    progress = RecordingProgress()
    build_handoff_dashboard(result, options, with_deltas=False, progress=progress)

    assert calls == {"audit": 1, "agents": 1, "skills": 1}
    assert progress.details[:3] == ["totals", "daily shape", "models"]
    assert "insights" in progress.details
    assert "forecasts" in progress.details


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


def test_build_handoff_dashboard_empty_window_onboards_with_doctor(tmp_path) -> None:
    dashboard = build_handoff_dashboard(
        _empty_load_result(),
        _options(tmp_path),
        with_deltas=False,
        budget_config={},
    )

    assert dashboard.executive_brief is not None
    titles = {f.title for f in dashboard.executive_brief.findings}
    assert "Verify data sources" in titles
    details = " ".join(f.detail for f in dashboard.executive_brief.findings)
    assert "caliper doctor" in details


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
    assert any(row.kind == "Session spike" for row in d.anomalies)
    assert not any(
        row.kind == "Project-day spike" and row.impact_usd == d.anomalies[0].impact_usd
        for row in d.anomalies
    )
    session_spike = next(row for row in d.anomalies if row.kind == "Session spike")
    assert "huge" not in session_spike.label
    assert "2026" in session_spike.label


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


def test_per_source_pressures_route_records_to_their_vendors(tmp_path) -> None:
    """Each panel must reflect ONLY that vendor's samples — no cross-contamination."""
    result = LoadResult(
        events=[],
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[
            # Codex: peak should be 80%.
            RateLimitSample(
                timestamp=dt.datetime(2026, 5, 12, 10, tzinfo=dt.UTC),
                path=tmp_path / "codex-a.jsonl",
                session_id="c1",
                plan_type="pro",
                limit_name="5-hour usage",
                primary_used_percent=40.0,
                vendor=VENDOR_OPENAI_CODEX,
            ),
            RateLimitSample(
                timestamp=dt.datetime(2026, 5, 12, 11, tzinfo=dt.UTC),
                path=tmp_path / "codex-b.jsonl",
                session_id="c1",
                plan_type="pro",
                limit_name="5-hour usage",
                primary_used_percent=80.0,
                vendor=VENDOR_OPENAI_CODEX,
            ),
            # Claude: peak should be 99% and the panel must NOT see 80%.
            RateLimitSample(
                timestamp=dt.datetime(2026, 5, 12, 12, tzinfo=dt.UTC),
                path=tmp_path / "claude.jsonl",
                session_id="cc1",
                plan_type="max",
                limit_name="5-hour usage",
                primary_used_percent=99.0,
                rate_limit_reached_type="primary",
                vendor=VENDOR_CLAUDE_CODE,
            ),
        ],
        warnings=[],
    )
    pressures = _build_rate_limit_pressures_by_source(result)
    # Ordering: Codex first, Claude Code second.
    assert [p.source for p in pressures] == [VENDOR_OPENAI_CODEX, VENDOR_CLAUDE_CODE]
    codex, claude = pressures
    assert codex.source_label == "Codex"
    assert codex.peak_primary_pct == 0.80  # NOT 0.99
    assert codex.latest_plan_type == "pro"
    assert codex.tone == "warn"  # 0.80 ≥ 0.75 threshold
    assert codex.reached_count == 0
    assert claude.source_label == "Claude Code"
    assert claude.peak_primary_pct == 0.99
    assert claude.latest_plan_type == "max"
    assert claude.tone == "critical"  # reached_count drives critical
    assert claude.reached_count == 1


def test_per_source_skips_empty_vendor_and_signal_free_records(tmp_path) -> None:
    """Records with no vendor or no rate-limit signal must not produce panels."""
    result = LoadResult(
        events=[],
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[
            # No vendor → dropped, even though it has a signal.
            RateLimitSample(
                timestamp=dt.datetime(2026, 5, 12, 10, tzinfo=dt.UTC),
                path=tmp_path / "orphan.jsonl",
                session_id="o1",
                primary_used_percent=50.0,
                vendor="",
            ),
            # No signal → dropped, even though vendor is set.
            RateLimitSample(
                timestamp=dt.datetime(2026, 5, 12, 11, tzinfo=dt.UTC),
                path=tmp_path / "silent.jsonl",
                session_id="s1",
                vendor=VENDOR_OPENAI_CODEX,
            ),
        ],
        warnings=[],
    )
    assert _build_rate_limit_pressures_by_source(result) == []


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
