from __future__ import annotations

import datetime as dt
import json

import pytest

from caliper.exporters import (
    ReceiptInputs,
    grafana_dashboard,
    month_bounds,
    render_grafana_dashboard,
    render_receipt_html,
    render_receipt_markdown,
)
from caliper.models import Aggregate, CostTotals, TokenTotals


def _aggregate(label: str, credits: float = 10.0, dollars: float = 1.0) -> Aggregate:
    totals = TokenTotals(events=1, input_tokens=100, output_tokens=10, total_tokens=110)
    costs = CostTotals(api_dollars=dollars, standard_credits=credits, adjusted_credits=credits)
    agg = Aggregate(key=label, label=label, totals=totals, costs=costs)
    agg.models.add("gpt-5.5")
    agg.service_tiers.add("standard")
    return agg


def _payload() -> ReceiptInputs:
    totals = _aggregate("Month", credits=1234.5, dollars=12.34)
    totals.totals.input_tokens = 1_000
    totals.totals.cached_input_tokens = 500
    totals.totals.output_tokens = 200
    totals.totals.reasoning_output_tokens = 50
    totals.totals.total_tokens = 1750
    totals.totals.events = 3
    totals.cache_savings.api_dollars = 9.87
    totals.cache_savings.adjusted_credits = 246.8
    return ReceiptInputs(
        month="2026-05",
        totals=totals,
        by_model=[_aggregate("gpt-5.5 / standard")],
        top_sessions=[_aggregate("12:00 | demo")],
        top_projects=[_aggregate("/tmp/project-alpha")],
        generated_at=dt.datetime(2026, 5, 13, 0, 0, tzinfo=dt.UTC),
    )


def test_month_bounds_returns_exclusive_next_month_end() -> None:
    start, end = month_bounds("2026-05", dt.UTC)
    assert start == dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 6, 1, tzinfo=dt.UTC)


def test_month_bounds_handles_february_leap_year() -> None:
    start, end = month_bounds("2024-02", dt.UTC)
    assert start == dt.datetime(2024, 2, 1, tzinfo=dt.UTC)
    assert end == dt.datetime(2024, 3, 1, tzinfo=dt.UTC)


def test_month_bounds_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        month_bounds("2026-13", dt.UTC)
    with pytest.raises(ValueError):
        month_bounds("not-a-month", dt.UTC)


def test_receipt_markdown_includes_sections_and_totals() -> None:
    text = render_receipt_markdown(_payload())
    assert "# Codex Meter Receipt — 2026-05" in text
    assert "## Totals" in text
    assert "## Models" in text
    assert "## Top sessions" in text
    assert "## Top projects" in text
    assert "1,234.50" in text
    assert "$12.34" in text
    assert "Cache savings" in text
    assert "$9.87" in text


def test_receipt_html_escapes_user_input() -> None:
    payload = _payload()
    payload.top_sessions[0].label = "<script>alert(1)</script>"
    html = render_receipt_html(payload)
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "Cache savings" in html


def test_grafana_dashboard_has_required_panels() -> None:
    dashboard = grafana_dashboard()
    assert dashboard["title"] == "Codex Meter"
    panel_titles = {panel["title"] for panel in dashboard["panels"]}
    assert "Credits used (current 5h)" in panel_titles
    assert "Burn rate (credits/hour)" in panel_titles
    assert "Primary window %" in panel_titles
    assert "Secondary window %" in panel_titles


def test_grafana_dashboard_serializable_json() -> None:
    text = render_grafana_dashboard("Codex Meter Test")
    parsed = json.loads(text)
    assert parsed["title"] == "Codex Meter Test"
    expressions = {panel["targets"][0]["expr"] for panel in parsed["panels"]}
    assert 'caliper_window_used_percent{window="primary"}' in expressions
    assert any("caliper_tokens_total" in expr for expr in expressions)
