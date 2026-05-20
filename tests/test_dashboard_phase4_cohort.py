"""Phase 4 dashboard power-ups: cohort delta table + agent sparkline."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from caliper.config import build_options
from caliper.dashboards import build_handoff_dashboard, render_dashboard
from caliper.dashboards.adapter import _build_cohort_deltas
from caliper.dashboards.data_models import CohortDeltaRow
from caliper.dashboards.html import render_cohort_deltas
from caliper.models import VENDOR_CLAUDE_CODE
from caliper.parser import load_usage
from caliper.pricing import load_rate_card


def _write_two_window_session(tmp_path: Path) -> None:
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    rows = []
    # Selected window: 10 days of higher activity
    for day in range(10):
        for hour in (9, 14):
            uid = f"cur-d{day}h{hour}"
            rows.append(
                {
                    "type": "assistant",
                    "sessionId": f"cur-{day}",
                    "uuid": uid,
                    "parentUuid": f"parent-{uid}",
                    "timestamp": f"2026-05-{11 + day:02d}T{hour:02d}:30:00.000Z",
                    "cwd": "/tmp/project-alpha",
                    "requestId": f"req-{uid}",
                    "message": {
                        "id": f"msg-{uid}",
                        "role": "assistant",
                        "model": "claude-sonnet-4-6-20260501",
                        "content": [{"type": "text", "text": "hi"}],
                        "usage": {"input_tokens": 2000, "output_tokens": 1000},
                    },
                }
            )
    # Prior window: 10 days of lower activity
    for day in range(10):
        uid = f"prev-d{day}"
        rows.append(
            {
                "type": "assistant",
                "sessionId": f"prev-{day}",
                "uuid": uid,
                "parentUuid": f"parent-{uid}",
                "timestamp": f"2026-05-{1 + day:02d}T10:00:00.000Z",
                "cwd": "/tmp/project-alpha",
                "requestId": f"req-{uid}",
                "message": {
                    "id": f"msg-{uid}",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6-20260501",
                    "content": [{"type": "text", "text": "hi"}],
                    "usage": {"input_tokens": 800, "output_tokens": 400},
                },
            }
        )
    (projects / "claude-session.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )


def _options(tmp_path: Path):
    return build_options(
        since="2026-05-11",
        until="2026-05-21",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )


def _load(monkeypatch, tmp_path: Path):
    _write_two_window_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    return load_usage(options), options


def test_cohort_delta_builder_compares_to_prior_window(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    rate_card = load_rate_card(options)
    from caliper.aggregation import aggregate_total

    total = aggregate_total(result, options, rate_card=rate_card)
    rows = _build_cohort_deltas(result, options, rate_card, total)
    assert rows, "expected cohort deltas when both windows have activity"
    labels = {row.label for row in rows}
    assert "Total cost" in labels
    assert "Events" in labels
    # Current window has more events than prior → tone should warn for events.
    by_label = {row.label: row for row in rows}
    assert by_label["Events"].delta_pct is not None
    assert by_label["Events"].delta_pct > 0


def test_render_cohort_deltas_emits_rows() -> None:
    rows = [
        CohortDeltaRow(
            label="Total cost",
            current_value="$100.00",
            previous_value="$50.00",
            delta_pct=1.0,
            delta_value=50.0,
            tone="warn",
        ),
    ]
    html = render_cohort_deltas(rows)
    assert 'data-section="cohort-deltas"' in html
    assert 'data-section="cohort-delta-row"' in html
    assert 'data-tone="warn"' in html
    assert "+100.0%" in html


def test_render_cohort_deltas_empty() -> None:
    assert render_cohort_deltas([]) == ""


def test_dashboard_carries_cohort_deltas_when_with_deltas(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    dashboard = build_handoff_dashboard(
        result, options, with_deltas=True, generated_at=dt.datetime(2026, 5, 21, tzinfo=dt.UTC)
    )
    assert dashboard.cohort_deltas, "expected cohort deltas on the dashboard"
    html = render_dashboard(dashboard)
    assert 'id="cohort-deltas"' in html


def test_dashboard_skips_cohort_deltas_when_with_deltas_false(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    dashboard = build_handoff_dashboard(
        result, options, with_deltas=False, generated_at=dt.datetime(2026, 5, 21, tzinfo=dt.UTC)
    )
    assert dashboard.cohort_deltas == []


def test_agent_row_sparkline_emitted_in_html(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    dashboard = build_handoff_dashboard(
        result, options, with_deltas=False, generated_at=dt.datetime(2026, 5, 21, tzinfo=dt.UTC)
    )
    if not dashboard.agents:
        return
    html = render_dashboard(dashboard)
    # When agents exist, the agent table should expose its sparkline column.
    assert 'data-section="agent-sparkline"' in html
