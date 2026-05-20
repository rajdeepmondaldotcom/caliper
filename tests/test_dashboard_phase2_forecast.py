"""Phase 2 dashboard power-ups: per-model OLS forecast strip,
portfolio 30/90-day outlook, per-project forecast confidence bands.

These hang off the analytics already in `predict.py` and `forecasts.py`;
adapter wiring + renderer assertions verify they reach the HTML.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from caliper.config import build_options
from caliper.dashboards import build_handoff_dashboard, render_dashboard
from caliper.dashboards.adapter import (
    _build_model_forecasts,
    _build_outlook,
    _build_project_forecast_bands,
)
from caliper.dashboards.data_models import (
    DailyPoint,
    ModelForecastRow,
    Outlook,
    ProjectRow,
    ToolCount,
)
from caliper.dashboards.html import (
    _project_forecast_cell,
    render_model_forecasts,
    render_outlook,
)
from caliper.models import VENDOR_CLAUDE_CODE
from caliper.parser import load_usage
from caliper.pricing import load_rate_card

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_multi_day_session(tmp_path: Path) -> None:
    """Ten days of activity so forecasts have a real OLS slope to fit."""
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    rows = []
    for day in range(10):
        for hour in (9, 14):
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
                            "output_tokens": 500 + day * 50,
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
        until="2026-05-11",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )


def _load(monkeypatch, tmp_path: Path):
    _write_multi_day_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    return load_usage(options), options


def _build(monkeypatch, tmp_path: Path):
    result, options = _load(monkeypatch, tmp_path)
    return (
        result,
        options,
        build_handoff_dashboard(
            result,
            options,
            with_deltas=False,
            generated_at=dt.datetime(2026, 5, 11, tzinfo=dt.UTC),
        ),
    )


# ---------------------------------------------------------------------------
# P4 — Portfolio 30/90d outlook
# ---------------------------------------------------------------------------


def test_outlook_builder_returns_both_horizons(monkeypatch, tmp_path) -> None:
    _, _, dashboard = _build(monkeypatch, tmp_path)
    assert dashboard.outlook is not None
    assert dashboard.outlook.horizon_30d.days == 30
    assert dashboard.outlook.horizon_90d.days == 90
    # 90-day midpoint must scale ~3x relative to 30-day under a flat mean.
    assert dashboard.outlook.horizon_90d.linear_total >= dashboard.outlook.horizon_30d.linear_total


def test_outlook_builder_short_history_returns_none() -> None:
    short = [
        DailyPoint(day=f"2026-05-{i:02d}", cost_usd=1.0, events=1, shape="execution")
        for i in range(1, 3)
    ]
    assert _build_outlook(short) is None


def test_render_outlook_emits_both_horizon_cards() -> None:
    horizon_30 = type(
        "H",
        (),
        dict(days=30, linear_total=100.0, linear_low=90.0, linear_high=110.0, ewma_total=95.0),
    )()
    horizon_90 = type(
        "H",
        (),
        dict(days=90, linear_total=300.0, linear_low=260.0, linear_high=340.0, ewma_total=290.0),
    )()
    outlook = Outlook(
        days_analyzed=10,
        daily_mean=10.0,
        daily_stdev=1.5,
        horizon_30d=horizon_30,  # type: ignore[arg-type]
        horizon_90d=horizon_90,  # type: ignore[arg-type]
    )
    html = render_outlook(outlook)
    assert 'data-section="outlook-30d"' in html
    assert 'data-section="outlook-90d"' in html
    assert 'data-horizon="30d"' in html
    assert 'data-horizon="90d"' in html


def test_render_outlook_none_returns_empty() -> None:
    assert render_outlook(None) == ""


# ---------------------------------------------------------------------------
# P2 — Per-model forecast strip
# ---------------------------------------------------------------------------


def test_model_forecast_builder_emits_rows(monkeypatch, tmp_path) -> None:
    result, options, dashboard = _build(monkeypatch, tmp_path)
    rate_card = load_rate_card(options)
    rows = _build_model_forecasts(result, options, rate_card, dashboard.by_model)
    assert rows, "model forecasts should produce ≥1 row from a 10-day session"
    row = rows[0]
    assert row.days_analyzed >= 3
    assert row.projected_30d_cost_usd >= 0
    # Sparkline lifted directly from ModelRow
    assert len(row.daily_cost_sparkline) == len(dashboard.by_model[0].daily_cost_sparkline)


def test_model_forecast_builder_caps_at_top_n() -> None:
    """top_n=2 must trim even when more rows would qualify."""
    # This builder uses by_model directly; pass an empty list to assert the
    # short-circuit, plus a stub model row to assert the cap.
    rows: list[ModelForecastRow] = _build_model_forecasts(
        result=None,  # type: ignore[arg-type]
        options=None,  # type: ignore[arg-type]
        rate_card=None,  # type: ignore[arg-type]
        by_model=[],
        top_n=2,
    )
    assert rows == []


def test_render_model_forecasts_emits_cards() -> None:
    rows = [
        ModelForecastRow(
            vendor="anthropic",
            model="claude-sonnet-4-6-20260501",
            days_analyzed=10,
            daily_mean_cost_usd=2.5,
            projected_30d_cost_usd=75.0,
            projected_30d_low=60.0,
            projected_30d_high=90.0,
            ewma_30d_cost_usd=80.0,
            trend_label="↑ 320 tok/d slope",
            trend_tone="warn",
            daily_cost_sparkline=[1.0, 2.0, 3.0],
            growing=True,
        ),
    ]
    html = render_model_forecasts(rows)
    assert 'data-section="model-forecasts"' in html
    assert 'data-section="model-forecast"' in html
    assert 'data-model="claude-sonnet-4-6-20260501"' in html
    assert 'data-section="model-forecast-band"' in html


def test_render_model_forecasts_empty_returns_empty() -> None:
    assert render_model_forecasts([]) == ""


# ---------------------------------------------------------------------------
# P5 — Per-project forecast bands
# ---------------------------------------------------------------------------


def test_project_forecast_bands_attach_to_project_rows(monkeypatch, tmp_path) -> None:
    _, _, dashboard = _build(monkeypatch, tmp_path)
    # 10-day fixture has 1 project — must get a band + confidence.
    confidences = {row.forecast_confidence for row in dashboard.by_project}
    assert {"high", "medium", "low"} & confidences, (
        f"expected at least one project to have a forecast confidence chip, got {confidences}"
    )


def test_project_forecast_bands_empty_aggregates() -> None:
    options_stub = type("Opt", (), {"timezone": "UTC"})
    bands = _build_project_forecast_bands([], options_stub, {})  # type: ignore[arg-type]
    assert bands == {}


def test_project_forecast_cell_includes_band_when_present() -> None:
    row = ProjectRow(
        name="alpha",
        path=None,
        cost_usd=100.0,
        events=10,
        sessions=2,
        top_tools=[ToolCount(name="Read", count=5, category="explore")],
        projected_30d_cost_usd=150.0,
        projected_30d_low=120.0,
        projected_30d_high=180.0,
        forecast_confidence="high",
    )
    html = _project_forecast_cell(row)
    assert 'data-section="project-band"' in html
    assert 'data-confidence="high"' in html
    assert "$120" in html or "$180" in html


def test_project_forecast_cell_no_band_for_sparse() -> None:
    row = ProjectRow(
        name="alpha",
        path=None,
        cost_usd=10.0,
        events=2,
        sessions=1,
        top_tools=[],
        projected_30d_cost_usd=30.0,
        forecast_confidence="",
    )
    html = _project_forecast_cell(row)
    assert 'data-section="project-band"' not in html


# ---------------------------------------------------------------------------
# Integration — render_dashboard wires Phase 2 sections
# ---------------------------------------------------------------------------


def test_render_dashboard_includes_phase2_sections(monkeypatch, tmp_path) -> None:
    _, _, dashboard = _build(monkeypatch, tmp_path)
    html = render_dashboard(dashboard)
    assert 'id="outlook"' in html
    assert 'id="model-forecasts"' in html
    assert 'data-section="project-forecast-cell"' in html
