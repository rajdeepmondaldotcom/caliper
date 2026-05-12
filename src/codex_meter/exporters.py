"""Export formats: monthly receipts (markdown/html) and Grafana dashboard JSON."""

from __future__ import annotations

import calendar
import datetime as dt
import html
import json
from collections.abc import Iterable
from dataclasses import dataclass

from codex_meter.models import Aggregate

DEFAULT_DASHBOARD_TITLE = "Codex Meter"


@dataclass(frozen=True)
class ReceiptInputs:
    month: str  # YYYY-MM
    totals: Aggregate
    by_model: list[Aggregate]
    top_sessions: list[Aggregate]
    top_projects: list[Aggregate]
    generated_at: dt.datetime


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
    last_day = calendar.monthrange(year_int, month_int)[1]
    start = dt.datetime(year_int, month_int, 1, tzinfo=tz)
    end = dt.datetime(year_int, month_int, last_day, 23, 59, 59, tzinfo=tz)
    return start, end


def _format_money(value: float) -> str:
    return f"${value:,.2f}"


def _format_credits(value: float) -> str:
    return f"{value:,.2f}"


def _format_int(value: int) -> str:
    return f"{value:,}"


def render_receipt_markdown(payload: ReceiptInputs) -> str:
    lines: list[str] = []
    lines.append(f"# Codex Meter Receipt — {payload.month}")
    lines.append("")
    lines.append(f"Generated: {payload.generated_at.isoformat()}")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | ---: |")
    lines.append(f"| Credits | {_format_credits(payload.totals.costs.adjusted_credits)} |")
    lines.append(f"| API $ | {_format_money(payload.totals.costs.api_dollars)} |")
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
    lines.append("| Label | Credits | API $ | Events | Tokens |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for row in rendered:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.label.replace("|", "\\|"),
                    _format_credits(row.costs.adjusted_credits),
                    _format_money(row.costs.api_dollars),
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
    sections.append(f"<h1>Codex Meter Receipt — {html.escape(payload.month)}</h1>")
    sections.append(f"<p><em>Generated: {payload.generated_at.isoformat()}</em></p>")
    sections.append("<h2>Totals</h2>")
    sections.append(
        "<table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>{name}</td><td>{value}</td></tr>"
            for name, value in (
                ("Credits", _format_credits(payload.totals.costs.adjusted_credits)),
                ("API $", _format_money(payload.totals.costs.api_dollars)),
                ("Events", _format_int(payload.totals.totals.events)),
                ("Tokens", _format_int(payload.totals.totals.total_tokens)),
                ("Input tokens", _format_int(payload.totals.totals.input_tokens)),
                ("Cached input", _format_int(payload.totals.totals.cached_input_tokens)),
                ("Output tokens", _format_int(payload.totals.totals.output_tokens)),
                ("Reasoning tokens", _format_int(payload.totals.totals.reasoning_output_tokens)),
            )
        )
        + "</tbody></table>"
    )
    sections.append(_html_section("Models", payload.by_model))
    sections.append(_html_section("Top sessions", payload.top_sessions))
    sections.append(_html_section("Top projects", payload.top_projects))
    body = "\n".join(sections)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>Codex Meter Receipt — {html.escape(payload.month)}</title>"
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
        f"<td>{_format_credits(row.costs.adjusted_credits)}</td>"
        f"<td>{_format_money(row.costs.api_dollars)}</td>"
        f"<td>{_format_int(row.totals.events)}</td>"
        f"<td>{_format_int(row.totals.total_tokens)}</td>"
        "</tr>"
        for row in rendered
    )
    return (
        f"<h2>{html.escape(title)}</h2>"
        "<table><thead><tr>"
        "<th>Label</th><th>Credits</th><th>API $</th><th>Events</th><th>Tokens</th>"
        "</tr></thead><tbody>"
        f"{body}"
        "</tbody></table>"
    )


def grafana_dashboard(title: str = DEFAULT_DASHBOARD_TITLE, datasource: str = "Prometheus") -> dict:
    """Generate a Grafana dashboard JSON tied to codex-meter Prometheus metrics."""
    return {
        "annotations": {"list": []},
        "editable": True,
        "schemaVersion": 39,
        "tags": ["codex-meter"],
        "title": title,
        "timezone": "",
        "time": {"from": "now-24h", "to": "now"},
        "refresh": "30s",
        "panels": [
            _stat_panel(
                id_=1,
                title="Credits used (current 5h)",
                expr="codex_meter_credits_used",
                unit="none",
                datasource=datasource,
                grid={"h": 5, "w": 6, "x": 0, "y": 0},
            ),
            _stat_panel(
                id_=2,
                title="Burn rate (credits/hour)",
                expr="codex_meter_burn_per_hour",
                unit="none",
                datasource=datasource,
                grid={"h": 5, "w": 6, "x": 6, "y": 0},
            ),
            _gauge_panel(
                id_=3,
                title="Primary window %",
                expr='codex_meter_window_used_percent{window="primary"}',
                datasource=datasource,
                grid={"h": 5, "w": 6, "x": 12, "y": 0},
            ),
            _gauge_panel(
                id_=4,
                title="Secondary window %",
                expr='codex_meter_window_used_percent{window="secondary"}',
                datasource=datasource,
                grid={"h": 5, "w": 6, "x": 18, "y": 0},
            ),
            _timeseries_panel(
                id_=5,
                title="Tokens by model / tier / kind",
                expr="sum by (model, tier, kind) (codex_meter_tokens_total)",
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
