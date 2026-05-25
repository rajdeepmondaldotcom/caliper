"""Export formats: monthly receipts (markdown/html) and Grafana dashboard JSON."""

from __future__ import annotations

import datetime as dt
import html
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from caliper.aggregation import aggregate_total
from caliper.models import Aggregate, LoadResult, RuntimeOptions
from caliper.pricing import load_rate_card
from caliper.timeutil import iso_z

DEFAULT_DASHBOARD_TITLE = "Caliper"


def session_compat_json(
    session_id: str,
    result: LoadResult,
    options: RuntimeOptions,
) -> str:
    """Render a single-session receipt in the legacy-compatible JSON shape.

    Previously private to ``caliper.cli`` as ``_compat_session_id_json``;
    promoted so the Textual TUI Receipt screen and any future exporter
    can share the same wire shape that ``caliper session --format
    compat-json`` already emits.
    """
    rate_card = load_rate_card(options)
    total = aggregate_total(result, options, rate_card=rate_card)
    entries = [
        {
            "timestamp": iso_z(event.timestamp),
            "inputTokens": event.usage.uncached_input_tokens,
            "outputTokens": event.usage.output_tokens,
            "cacheCreationTokens": (
                event.usage.cache_creation_input_tokens + event.usage.cache_creation_input_1h_tokens
            ),
            "cacheReadTokens": event.usage.cache_read_input_tokens,
            "model": event.raw_model or event.model or "unknown",
            "costUSD": 0,
        }
        for event in sorted(result.events, key=lambda item: item.timestamp)
    ]
    return (
        json.dumps(
            {
                "sessionId": session_id,
                "totalCost": float(total.costs.cost_usd),
                "totalTokens": total.totals.total_tokens,
                "entries": entries,
            },
            indent=2,
        )
        + "\n"
    )


@dataclass(frozen=True)
class ReceiptInputs:
    month: str  # YYYY-MM
    totals: Aggregate
    by_model: list[Aggregate]
    top_sessions: list[Aggregate]
    top_projects: list[Aggregate]
    generated_at: dt.datetime
    tier_sources: dict[str, int] | None = None
    insights: list[str] | None = None
    warning_count: int = 0
    pricing_status: str = "exact"
    pricing_warnings: list[str] | None = None
    accuracy_status: str = "exact"
    accuracy_reasons: list[str] | None = None


def month_bounds(month: str, tz: dt.tzinfo) -> tuple[dt.datetime, dt.datetime]:
    """Parse 'YYYY-MM' into [start, end) local-tz datetimes."""
    try:
        year, month_num = month.split("-")
        year_int = int(year)
        month_int = int(month_num)
    except ValueError as exc:
        raise ValueError(f"Invalid --month {month!r}; expected YYYY-MM") from exc
    if not 1 <= month_int <= 12:
        raise ValueError(f"Month must be 1..12, got {month_int}")
    start = dt.datetime(year_int, month_int, 1, tzinfo=tz)
    if month_int == 12:
        end = dt.datetime(year_int + 1, 1, 1, tzinfo=tz)
    else:
        end = dt.datetime(year_int, month_int + 1, 1, tzinfo=tz)
    return start, end


def _format_money(value: Any) -> str:
    return f"${float(value):,.2f}"


def _format_int(value: int) -> str:
    return f"{value:,}"


def render_receipt_markdown(payload: ReceiptInputs) -> str:
    lines: list[str] = []
    lines.append(f"# Caliper Receipt — {payload.month}")
    lines.append("")
    lines.append(f"Generated: {payload.generated_at.isoformat()}")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | ---: |")
    lines.append(f"| Cost $ | {_format_money(payload.totals.costs.cost_usd)} |")
    lines.append(f"| Cache discount $ | {_format_money(payload.totals.cache_savings.cost_usd)} |")
    lines.append(f"| Events | {_format_int(payload.totals.totals.events)} |")
    lines.append(f"| Tokens | {_format_int(payload.totals.totals.total_tokens)} |")
    lines.append(
        f"| Input tokens | {_format_int(payload.totals.totals.input_tokens)} (cached "
        f"{_format_int(payload.totals.totals.cached_input_tokens)}) |"
    )
    lines.append(f"| Output tokens | {_format_int(payload.totals.totals.output_tokens)} |")
    lines.append(
        f"| Reasoning tokens | {_format_int(payload.totals.totals.reasoning_output_tokens)} |"
    )
    if payload.tier_sources:
        sources = ", ".join(
            f"{key}={value:,}" for key, value in sorted(payload.tier_sources.items())
        )
        lines.append(f"| Tier sources | {sources} |")
    if payload.warning_count:
        lines.append(f"| Parser warnings | {_format_int(payload.warning_count)} |")
    if payload.pricing_status != "exact" or payload.pricing_warnings:
        warnings = "; ".join(payload.pricing_warnings or []) or payload.pricing_status
        lines.append(f"| Pricing status | {payload.pricing_status}: {warnings} |")
    if payload.accuracy_status != "exact" or payload.accuracy_reasons:
        reasons = "; ".join(payload.accuracy_reasons or []) or payload.accuracy_status
        lines.append(f"| Accuracy | {payload.accuracy_status}: {reasons} |")
    lines.append("")
    if payload.insights:
        lines.append("## Insights")
        lines.append("")
        for insight in payload.insights:
            lines.append(f"- {insight}")
        lines.append("")
    lines.extend(_section_table("Models", payload.by_model))
    lines.extend(_section_table("Top sessions", payload.top_sessions))
    lines.extend(_section_table("Top projects", payload.top_projects))
    return "\n".join(lines) + "\n"


def _section_table(title: str, rows: Iterable[Aggregate]) -> list[str]:
    rendered = list(rows)
    if not rendered:
        return [f"## {title}", "", "_No data for this month._", ""]
    lines: list[str] = [f"## {title}", ""]
    lines.append("| Label | Cost $ | Events | Tokens |")
    lines.append("| --- | ---: | ---: | ---: |")
    for row in rendered:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.label.replace("|", "\\|"),
                    _format_money(row.costs.cost_usd),
                    _format_int(row.totals.events),
                    _format_int(row.totals.total_tokens),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def render_receipt_html(payload: ReceiptInputs) -> str:
    sections: list[str] = []
    sections.append(f"<h1>Caliper Receipt — {html.escape(payload.month)}</h1>")
    sections.append(f"<p><em>Generated: {payload.generated_at.isoformat()}</em></p>")
    sections.append("<h2>Totals</h2>")
    sections.append(
        "<table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>{name}</td><td>{value}</td></tr>"
            for name, value in (
                ("Cost $", _format_money(payload.totals.costs.cost_usd)),
                (
                    "Cache discount $",
                    _format_money(payload.totals.cache_savings.cost_usd),
                ),
                ("Events", _format_int(payload.totals.totals.events)),
                ("Tokens", _format_int(payload.totals.totals.total_tokens)),
                ("Input tokens", _format_int(payload.totals.totals.input_tokens)),
                ("Cached input", _format_int(payload.totals.totals.cached_input_tokens)),
                ("Output tokens", _format_int(payload.totals.totals.output_tokens)),
                ("Reasoning tokens", _format_int(payload.totals.totals.reasoning_output_tokens)),
                (
                    "Tier sources",
                    ", ".join(
                        f"{key}={value:,}"
                        for key, value in sorted((payload.tier_sources or {}).items())
                    )
                    or "—",
                ),
                ("Parser warnings", _format_int(payload.warning_count)),
                (
                    "Pricing status",
                    (f"{payload.pricing_status}: {'; '.join(payload.pricing_warnings or [])}")
                    if payload.pricing_status != "exact" or payload.pricing_warnings
                    else "exact",
                ),
                (
                    "Accuracy",
                    (f"{payload.accuracy_status}: {'; '.join(payload.accuracy_reasons or [])}")
                    if payload.accuracy_status != "exact" or payload.accuracy_reasons
                    else "exact",
                ),
            )
        )
        + "</tbody></table>"
    )
    if payload.insights:
        sections.append(
            "<h2>Insights</h2><ul>"
            + "".join(f"<li>{html.escape(item)}</li>" for item in payload.insights)
            + "</ul>"
        )
    sections.append(_html_section("Models", payload.by_model))
    sections.append(_html_section("Top sessions", payload.top_sessions))
    sections.append(_html_section("Top projects", payload.top_projects))
    body = "\n".join(sections)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>Caliper Receipt — {html.escape(payload.month)}</title>"
        "<style>"
        "body{font-family:system-ui,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;}"
        "table{border-collapse:collapse;width:100%;margin-bottom:1.5rem;}"
        "th,td{border:1px solid #ddd;padding:.4rem .6rem;}"
        "th{background:#f5f5f5;text-align:left;}"
        "td:last-child,th:last-child{text-align:right;}"
        "</style></head><body>"
        f"{body}"
        "</body></html>"
    )


def _html_section(title: str, rows: Iterable[Aggregate]) -> str:
    rendered = list(rows)
    if not rendered:
        return f"<h2>{html.escape(title)}</h2><p><em>No data for this month.</em></p>"
    body = "".join(
        "<tr>"
        f"<td>{html.escape(row.label)}</td>"
        f"<td>{_format_money(row.costs.cost_usd)}</td>"
        f"<td>{_format_int(row.totals.events)}</td>"
        f"<td>{_format_int(row.totals.total_tokens)}</td>"
        "</tr>"
        for row in rendered
    )
    return (
        f"<h2>{html.escape(title)}</h2>"
        "<table><thead><tr>"
        "<th>Label</th><th>Cost $</th><th>Events</th><th>Tokens</th>"
        "</tr></thead><tbody>"
        f"{body}"
        "</tbody></table>"
    )


def grafana_dashboard(title: str = DEFAULT_DASHBOARD_TITLE, datasource: str = "Prometheus") -> dict:
    """Generate a Grafana dashboard JSON tied to caliper Prometheus metrics."""
    return {
        "annotations": {"list": []},
        "editable": True,
        "schemaVersion": 39,
        "tags": ["caliper"],
        "title": title,
        "timezone": "",
        "time": {"from": "now-24h", "to": "now"},
        "refresh": "30s",
        "panels": [
            _stat_panel(
                id_=1,
                title="Cost $ used (current 5h)",
                expr="caliper_cost_usd",
                unit="none",
                datasource=datasource,
                grid={"h": 5, "w": 6, "x": 0, "y": 0},
            ),
            _stat_panel(
                id_=2,
                title="Burn rate (% points/hour)",
                expr="caliper_burn_per_hour",
                unit="none",
                datasource=datasource,
                grid={"h": 5, "w": 6, "x": 6, "y": 0},
            ),
            _gauge_panel(
                id_=3,
                title="Primary window %",
                expr='caliper_window_used_percent{window="primary"}',
                datasource=datasource,
                grid={"h": 5, "w": 6, "x": 12, "y": 0},
            ),
            _gauge_panel(
                id_=4,
                title="Secondary window %",
                expr='caliper_window_used_percent{window="secondary"}',
                datasource=datasource,
                grid={"h": 5, "w": 6, "x": 18, "y": 0},
            ),
            _timeseries_panel(
                id_=5,
                title="Tokens by model / tier / kind",
                expr="sum by (model, tier, kind) (caliper_tokens_total)",
                datasource=datasource,
                grid={"h": 10, "w": 24, "x": 0, "y": 5},
            ),
        ],
    }


def _stat_panel(
    *,
    id_: int,
    title: str,
    expr: str,
    unit: str,
    datasource: str,
    grid: dict,
) -> dict:
    return {
        "id": id_,
        "type": "stat",
        "title": title,
        "gridPos": grid,
        "datasource": datasource,
        "fieldConfig": {"defaults": {"unit": unit, "decimals": 2}},
        "targets": [{"expr": expr, "refId": "A"}],
    }


def _gauge_panel(*, id_: int, title: str, expr: str, datasource: str, grid: dict) -> dict:
    return {
        "id": id_,
        "type": "gauge",
        "title": title,
        "gridPos": grid,
        "datasource": datasource,
        "fieldConfig": {
            "defaults": {
                "unit": "percent",
                "min": 0,
                "max": 100,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"value": 0, "color": "green"},
                        {"value": 80, "color": "orange"},
                        {"value": 100, "color": "red"},
                    ],
                },
            }
        },
        "targets": [{"expr": expr, "refId": "A"}],
    }


def _timeseries_panel(*, id_: int, title: str, expr: str, datasource: str, grid: dict) -> dict:
    return {
        "id": id_,
        "type": "timeseries",
        "title": title,
        "gridPos": grid,
        "datasource": datasource,
        "fieldConfig": {"defaults": {"unit": "none"}},
        "targets": [{"expr": expr, "refId": "A"}],
    }


def render_grafana_dashboard(title: str = DEFAULT_DASHBOARD_TITLE) -> str:
    return json.dumps(grafana_dashboard(title=title), indent=2) + "\n"
