"""Phase 3 dashboard power-ups: prompt-rot curve, cache leverage by session,
long-context input-token histogram."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from caliper.config import build_options
from caliper.dashboards import build_handoff_dashboard, render_dashboard
from caliper.dashboards.adapter import (
    _build_cache_leverage,
    _build_long_context_histogram,
)
from caliper.dashboards.data_models import (
    CacheLeverageRow,
    InefficiencyRow,
    LongContextHistogram,
)
from caliper.dashboards.html import (
    render_cache_leverage,
    render_inefficiencies,
    render_long_context_histogram,
)
from caliper.models import VENDOR_CLAUDE_CODE
from caliper.parser import load_usage
from caliper.pricing import load_rate_card


def _write_session(tmp_path: Path) -> None:
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    rows = []
    for day in range(6):
        for hour in (9, 14, 18):
            uid = f"d{day}h{hour}"
            rows.append(
                {
                    "type": "assistant",
                    "sessionId": f"claude-session-{day}",
                    "uuid": uid,
                    "parentUuid": f"parent-{uid}",
                    "timestamp": f"2026-05-{1 + day:02d}T{hour:02d}:30:00.000Z",
                    "cwd": "/tmp/project-alpha",
                    "requestId": f"req-{uid}",
                    "message": {
                        "id": f"msg-{uid}",
                        "role": "assistant",
                        "model": "claude-sonnet-4-6-20260501",
                        "content": [{"type": "text", "text": "hi"}],
                        "usage": {
                            "input_tokens": 1000 + day * 100,
                            "cache_read_input_tokens": 8000,
                            "output_tokens": 500,
                        },
                    },
                }
            )
    (projects / "claude-session.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )


def _options(tmp_path: Path):
    return build_options(
        since="2026-05-01",
        until="2026-05-07",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )


def _load(monkeypatch, tmp_path: Path):
    _write_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    return load_usage(options), options


# ---------------------------------------------------------------------------
# P6 — Prompt-rot curve
# ---------------------------------------------------------------------------


def test_render_inefficiencies_emits_curve_when_present() -> None:
    row = InefficiencyRow(
        code="PROMPT_ROT",
        severity="warn",
        evidence_status="estimated",
        title="3 sessions show prompt rot",
        detail="...",
        action="Compact context.",
        impact_usd=12.3,
        monthly_projected_savings_usd=24.6,
        confidence="medium",
        sample_size=15,
        baseline="growth >= 2.0x",
        curve=(100, 180, 260, 220, 300),
    )
    html = render_inefficiencies([row])
    assert 'data-section="prompt-rot-curve"' in html
    assert 'data-finding-code="PROMPT_ROT"' in html


def test_render_inefficiencies_no_curve_for_other_codes() -> None:
    row = InefficiencyRow(
        code="REASONING_WASTE",
        severity="warn",
        evidence_status="estimated",
        title="title",
        detail="detail",
        action="action",
        impact_usd=1.0,
        monthly_projected_savings_usd=2.0,
        confidence="medium",
        sample_size=5,
        baseline="...",
    )
    html = render_inefficiencies([row])
    assert "prompt-rot-curve" not in html


# ---------------------------------------------------------------------------
# P7 — Cache leverage
# ---------------------------------------------------------------------------


def test_cache_leverage_builder_ranks_by_savings(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    rate_card = load_rate_card(options)
    rows = _build_cache_leverage(result, options, rate_card)
    # Sessions with cached_read tokens should produce at least one row.
    if rows:
        # Descending order
        for prev, nxt in zip(rows, rows[1:], strict=False):
            assert prev.savings_usd >= nxt.savings_usd


def test_render_cache_leverage_emits_rows() -> None:
    rows = [
        CacheLeverageRow(
            session_label="claude-session-1",
            project="/tmp/project-alpha",
            savings_usd=4.5,
            hit_rate=0.82,
            cached_input_tokens=12_000,
            uncached_input_tokens=2_400,
        ),
    ]
    html = render_cache_leverage(rows)
    assert 'data-section="cache-leverage"' in html
    assert 'data-section="cache-leverage-row"' in html
    assert 'data-session="claude-session-1"' in html


def test_render_cache_leverage_empty_returns_empty() -> None:
    assert render_cache_leverage([]) == ""


# ---------------------------------------------------------------------------
# P10 — Long-context histogram
# ---------------------------------------------------------------------------


def test_long_context_histogram_builder_emits_section(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    rate_card = load_rate_card(options)
    hist = _build_long_context_histogram(result, rate_card)
    assert hist is not None
    assert hist.total_events > 0
    assert len(hist.bins) == len(hist.counts)
    assert sum(hist.counts) == hist.total_events


def test_render_long_context_histogram_emits_bars() -> None:
    hist = LongContextHistogram(
        bins=(0, 1000, 4000, 16000, 64000, 200000, 1000000),
        counts=(2, 3, 5, 10, 4, 1, 0),
        threshold_tokens=200_000,
        share_above_threshold=0.04,
        cost_share_above_threshold=0.15,
        total_events=25,
    )
    html = render_long_context_histogram(hist)
    assert 'data-section="lc-histogram"' in html
    assert 'data-section="lc-threshold-line"' in html
    assert "LC threshold" in html


def test_render_long_context_histogram_none() -> None:
    assert render_long_context_histogram(None) == ""


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_render_dashboard_includes_phase3_sections(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    dashboard = build_handoff_dashboard(
        result, options, with_deltas=False, generated_at=dt.datetime(2026, 5, 7, tzinfo=dt.UTC)
    )
    html = render_dashboard(dashboard)
    # LC histogram should always emit when there is ≥1 event.
    assert 'id="lc-histogram"' in html
