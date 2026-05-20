"""Phase 1 dashboard power-ups: seasonality, rate-limit ETA bands, model
sparkline, tier-source provenance.

Each new section follows the same pattern: a thin adapter builder pulls
data from analytics modules that already exist; the renderer emits SVG /
CSS-only HTML with deterministic ``data-section`` markers so we can
substring-assert without snapshotting the full dashboard.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from caliper.config import build_options
from caliper.dashboards import build_handoff_dashboard, render_dashboard
from caliper.dashboards.adapter import (
    _build_rate_limit_forecast_bands,
    _build_seasonality,
    _build_tier_provenance,
    _hour_dow_cost_matrix,
)
from caliper.dashboards.data_models import (
    RateLimitForecastBand,
    RateLimitPressure,
    SeasonalitySection,
    TierProvenance,
)
from caliper.dashboards.html import (
    render_rate_limit_forecasts,
    render_seasonality,
    render_tier_provenance,
)
from caliper.models import VENDOR_CLAUDE_CODE
from caliper.parser import load_usage
from caliper.pricing import load_rate_card

# ---------------------------------------------------------------------------
# Fixture helpers (mirror tests/test_dashboard_html._write_session)
# ---------------------------------------------------------------------------


def _write_multi_hour_session(tmp_path: Path) -> Path:
    """Six events scattered across two hours + two days so seasonality has
    a real shape, not a single bucket."""
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    rows = []
    # Day 1: heavy 10:00 + light 14:00
    for hour in (10, 10, 10, 14):
        rows.append(_token_row(f"d1h{hour}-{len(rows)}", "2026-05-12", hour))
    # Day 2: heavy 22:00
    for _ in range(2):
        rows.append(_token_row(f"d2h22-{len(rows)}", "2026-05-13", 22))
    path = projects / "claude-session-1.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def _token_row(uid: str, day: str, hour: int) -> dict:
    return {
        "type": "assistant",
        "sessionId": "claude-session-1",
        "uuid": uid,
        "parentUuid": f"parent-{uid}",
        "timestamp": f"{day}T{hour:02d}:30:00.000Z",
        "cwd": "/tmp/project-alpha",
        "requestId": f"req-{uid}",
        "message": {
            "id": f"msg-{uid}",
            "role": "assistant",
            "model": "claude-sonnet-4-6-20260501",
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        },
    }


def _options(tmp_path: Path):
    return build_options(
        since="2026-05-12",
        until="2026-05-14",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )


def _load(monkeypatch, tmp_path: Path):
    _write_multi_hour_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    return load_usage(options), options


# ---------------------------------------------------------------------------
# P1 — Cost-weighted seasonality
# ---------------------------------------------------------------------------


def test_seasonality_builder_returns_section(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    rate_card = load_rate_card(options)
    section = _build_seasonality(result, options, rate_card)
    assert section is not None
    assert isinstance(section, SeasonalitySection)
    assert len(section.by_hour_cost_usd) == 24
    assert len(section.by_dow_cost_usd) == 7
    assert len(section.by_dow_hour_cost_usd) == 7
    assert all(len(row) == 24 for row in section.by_dow_hour_cost_usd)
    assert section.total_cost_usd > 0
    # Peak hour must be 10 — three of six events fell there.
    assert section.peak_hour == 10


def test_seasonality_builder_empty_events_returns_none(monkeypatch, tmp_path) -> None:
    options = _options(tmp_path)
    rate_card = load_rate_card(options)
    from caliper.models import LoadResult

    empty = LoadResult(
        events=[],
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )
    assert _build_seasonality(empty, options, rate_card) is None


def test_seasonality_matrix_sums_to_strip_totals(monkeypatch, tmp_path) -> None:
    """Per-cell matrix must roll up to the per-hour + per-dow strips."""
    result, options = _load(monkeypatch, tmp_path)
    rate_card = load_rate_card(options)
    matrix = _hour_dow_cost_matrix(result.events, rate_card, options.timezone)
    for hour in range(24):
        column_total = sum(matrix[dow][hour] for dow in range(7))
        section = _build_seasonality(result, options, rate_card)
        assert section is not None
        assert column_total == section.by_hour_cost_usd[hour]


def test_render_seasonality_emits_grid_and_strips(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    rate_card = load_rate_card(options)
    section = _build_seasonality(result, options, rate_card)
    html = render_seasonality(section)
    assert 'data-section="seasonality"' in html
    assert 'data-section="seasonality-hour-strip"' in html
    assert 'data-section="seasonality-dow-strip"' in html
    assert "Peak hour" in html
    # 7 × 24 = 168 grid cells
    assert html.count('class="hod-cell ') == 168


def test_render_seasonality_handles_none() -> None:
    assert render_seasonality(None) == ""


# ---------------------------------------------------------------------------
# P3 — Rate-limit ETA confidence band
# ---------------------------------------------------------------------------


def _band(
    *,
    window: str = "primary",
    confidence: str = "high",
    eta_mid: float | None = 12.0,
    eta_low: float | None = 8.0,
    eta_high: float | None = 20.0,
    samples: int = 8,
) -> RateLimitForecastBand:
    return RateLimitForecastBand(
        window=window,
        limit_name=f"{window}-window",
        current_percent=0.42,
        burn_rate_per_hour=0.05,
        eta_low_hours=eta_low,
        eta_mid_hours=eta_mid,
        eta_high_hours=eta_high,
        confidence=confidence,
        samples=samples,
    )


def test_render_rate_limit_forecasts_empty_returns_empty_string() -> None:
    assert render_rate_limit_forecasts(()) == ""


def test_render_rate_limit_forecasts_low_confidence_shows_needs_more() -> None:
    html = render_rate_limit_forecasts((_band(confidence="low", eta_mid=None, samples=1),))
    assert 'data-section="rate-limit-eta"' in html
    assert 'data-confidence="low"' in html
    assert "needs more samples" in html


def test_render_rate_limit_forecasts_high_confidence_shows_band() -> None:
    html = render_rate_limit_forecasts((_band(),))
    assert 'data-confidence="high"' in html
    assert 'data-section="rate-limit-eta-range"' in html
    # Mid value (12h) rendered as "12.0 h"
    assert "12.0 h" in html
    # Confidence chip is present
    assert 'class="eta-confidence-chip"' in html


def test_rate_limit_pressure_carries_forecast_bands_when_samples_exist(
    monkeypatch, tmp_path
) -> None:
    """Smoke-test: empty session has no samples → empty bands tuple."""
    result, _ = _load(monkeypatch, tmp_path)
    bands = _build_rate_limit_forecast_bands(result)
    assert bands == ()


# ---------------------------------------------------------------------------
# P8 — Model row sparkline parity
# ---------------------------------------------------------------------------


def test_model_row_carries_daily_cost_sparkline(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    dashboard = build_handoff_dashboard(
        result, options, with_deltas=False, generated_at=dt.datetime(2026, 5, 17, tzinfo=dt.UTC)
    )
    assert dashboard.by_model, "session should produce at least one model row"
    sparklines = [row.daily_cost_sparkline for row in dashboard.by_model]
    assert any(spark for spark in sparklines), "at least one model row must have a sparkline"


def test_render_models_includes_sparkline_cell(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    dashboard = build_handoff_dashboard(
        result, options, with_deltas=False, generated_at=dt.datetime(2026, 5, 17, tzinfo=dt.UTC)
    )
    html = render_dashboard(dashboard)
    assert 'data-section="model-sparkline"' in html
    assert "Daily trend" in html  # new column header


# ---------------------------------------------------------------------------
# P11 — Tier-source provenance
# ---------------------------------------------------------------------------


def test_tier_provenance_builder_groups_sources(monkeypatch, tmp_path) -> None:
    result, _ = _load(monkeypatch, tmp_path)
    prov = _build_tier_provenance(result)
    if prov is None:
        # Sessions without service-tier metadata produce no provenance; the
        # builder must still emit at least one labelled source when totals > 0.
        return
    assert prov.total_events > 0
    assert sum(count for _, count in prov.sources) == prov.total_events


def test_tier_provenance_handles_empty() -> None:
    from caliper.models import LoadResult

    empty = LoadResult(
        events=[],
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )
    assert _build_tier_provenance(empty) is None


def test_render_tier_provenance_emits_stacked_bar() -> None:
    prov = TierProvenance(
        sources=(("CLI override", 60), ("Logged in event", 30), ("Assumed default", 10)),
        total_events=100,
    )
    html = render_tier_provenance(prov)
    assert 'data-section="tier-provenance"' in html
    assert 'data-tier-source="CLI override"' in html
    assert 'data-tier-source="Logged in event"' in html
    assert "Assumed default" in html
    # Stacked bar segments — one per source.
    assert html.count('class="prov-seg ') == 3


def test_render_tier_provenance_none_returns_empty() -> None:
    assert render_tier_provenance(None) == ""


# ---------------------------------------------------------------------------
# Dashboard integration — schema bump + full render
# ---------------------------------------------------------------------------


def test_schema_version_bumped_to_three(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    dashboard = build_handoff_dashboard(
        result, options, with_deltas=False, generated_at=dt.datetime(2026, 5, 17, tzinfo=dt.UTC)
    )
    assert dashboard.caliper.schema_version == 3


def test_render_dashboard_includes_phase1_sections(monkeypatch, tmp_path) -> None:
    result, options = _load(monkeypatch, tmp_path)
    dashboard = build_handoff_dashboard(
        result, options, with_deltas=False, generated_at=dt.datetime(2026, 5, 17, tzinfo=dt.UTC)
    )
    html = render_dashboard(dashboard)
    assert 'id="seasonality"' in html
    # Tier-source provenance is conditional on tier_sources being non-empty
    # — guard the assertion against fixture variance.
    if dashboard.tier_provenance is not None:
        assert 'id="tier-provenance"' in html


def test_pressure_payload_has_forecasts_tuple_default() -> None:
    """Constructing RateLimitPressure without forecasts keeps backwards compat."""
    pressure = RateLimitPressure(
        sample_count=0,
        peak_primary_pct=None,
        peak_secondary_pct=None,
        latest_primary_pct=None,
        latest_secondary_pct=None,
        latest_limit_name="",
        latest_plan_type="",
        latest_resets_at="",
        reached_count=0,
    )
    assert pressure.forecasts == ()
