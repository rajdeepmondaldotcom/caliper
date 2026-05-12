from __future__ import annotations

import csv
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

from codex_meter.aggregation import aggregate_model_mode, aggregate_total, window_label
from codex_meter.models import Aggregate, LoadResult, RuntimeOptions
from codex_meter.pricing import PRICING_SOURCES
from codex_meter.timeutil import iso_z


def format_int(value: int) -> str:
    return f"{value:,}"


def redact(text: str, enabled: bool, limit: int = 72) -> str:
    clean = " ".join(str(text).split())
    if enabled:
        return clean
    if not clean:
        return ""
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def aggregate_to_dict(item: Aggregate) -> dict:
    return {
        "key": item.key,
        "label": item.label,
        "events": item.totals.events,
        "input_tokens": item.totals.input_tokens,
        "cached_input_tokens": item.totals.cached_input_tokens,
        "uncached_input_tokens": item.totals.uncached_input_tokens,
        "output_tokens": item.totals.output_tokens,
        "reasoning_output_tokens": item.totals.reasoning_output_tokens,
        "total_tokens": item.totals.total_tokens,
        "credits": item.costs.adjusted_credits,
        "standard_credits": item.costs.standard_credits,
        "api_dollars": item.costs.api_dollars,
        "models": sorted(item.models),
        "service_tiers": sorted(item.service_tiers),
        "plan_types": sorted(item.plan_types),
        "long_context_events": item.long_context_events,
        "unknown_model_events": item.unknown_model_events,
        "unknown_tier_events": item.unknown_tier_events,
    }


def report_payload(
    result: LoadResult,
    options: RuntimeOptions,
    rows: list[Aggregate],
    command: str,
) -> dict:
    total = aggregate_total(result, options)
    return {
        "command": command,
        "generated_at": iso_z(options.end),
        "window": {
            "start": iso_z(options.start),
            "end": iso_z(options.end),
            "label": window_label(options.start, options.end, options.timezone),
            "timezone": options.timezone,
        },
        "totals": aggregate_to_dict(total) | {"duplicates": result.duplicates},
        "breakdowns": [aggregate_to_dict(row) for row in rows],
        "model_mode": [aggregate_to_dict(row) for row in aggregate_model_mode(result, options)],
        "pricing": {
            "mode": options.pricing_mode,
            "offline": options.offline,
            "sources": [asdict(source) for source in PRICING_SOURCES],
        },
        "metadata": {
            "session_root": str(options.session_root),
            "state_db": str(options.state_db),
            "tier_sources": result.tier_sources,
            "plan_types": sorted(result.plan_types),
        },
        "warnings": result.warnings,
    }


def write_output(text: str, output: Path | None) -> None:
    if output:
        output.expanduser().write_text(text)
    else:
        sys.stdout.write(text)


def render_table(
    result: LoadResult, options: RuntimeOptions, rows: list[Aggregate], title: str
) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=100 if options.compact else None)
    total = aggregate_total(result, options)
    console.print(f"[bold]{title}[/bold]")
    console.print(f"Window: {window_label(options.start, options.end, options.timezone)}")
    console.print(f"Session root: {options.session_root}")
    if result.warnings:
        for warning in result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
    console.print()

    table = Table(show_lines=False)
    table.add_column("Group")
    table.add_column("Models")
    table.add_column("Input", justify="right")
    table.add_column("Cached", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Credits", justify="right")
    table.add_column("API $", justify="right")
    for row in rows:
        table.add_row(
            redact(row.label, options.show_prompts),
            "\n".join(sorted(row.models)) or "-",
            format_int(row.totals.input_tokens),
            format_int(row.totals.cached_input_tokens),
            format_int(row.totals.output_tokens),
            format_int(row.totals.total_tokens),
            f"{row.costs.adjusted_credits:,.2f}",
            f"${row.costs.api_dollars:,.2f}",
        )
    table.add_section()
    table.add_row(
        "Total",
        "\n".join(sorted(total.models)) or "-",
        format_int(total.totals.input_tokens),
        format_int(total.totals.cached_input_tokens),
        format_int(total.totals.output_tokens),
        format_int(total.totals.total_tokens),
        f"{total.costs.adjusted_credits:,.2f}",
        f"${total.costs.api_dollars:,.2f}",
    )
    console.print(table)
    console.print()
    events_text = format_int(total.totals.events)
    duplicates_text = format_int(result.duplicates)
    console.print(f"Events: {events_text} | Duplicates skipped: {duplicates_text}")
    if total.costs.adjusted_credits != total.costs.standard_credits:
        console.print(f"Standard-mode baseline: {total.costs.standard_credits:,.2f} credits")
    if result.tier_sources:
        sources = ", ".join(
            f"{key}={format_int(value)}" for key, value in sorted(result.tier_sources.items())
        )
        console.print(f"Service-tier sources: {sources}")
    if result.plan_types:
        console.print(f"Plan types: {', '.join(sorted(result.plan_types))}")
    return buffer.getvalue()


def render_json(
    result: LoadResult, options: RuntimeOptions, rows: list[Aggregate], command: str
) -> str:
    return json.dumps(report_payload(result, options, rows, command), indent=2) + "\n"


def render_csv(rows: list[Aggregate]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "key",
            "label",
            "events",
            "input_tokens",
            "cached_input_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "total_tokens",
            "credits",
            "standard_credits",
            "api_dollars",
            "models",
            "service_tiers",
        ],
    )
    writer.writeheader()
    for row in rows:
        item = aggregate_to_dict(row)
        item["models"] = ",".join(item["models"])
        item["service_tiers"] = ",".join(item["service_tiers"])
        writer.writerow({key: item[key] for key in writer.fieldnames or []})
    return output.getvalue()


def render_markdown(rows: list[Aggregate]) -> str:
    headers = ["Group", "Events", "Total tokens", "Credits", "API $"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.label.replace("|", "\\|"),
                    str(row.totals.events),
                    str(row.totals.total_tokens),
                    f"{row.costs.adjusted_credits:.2f}",
                    f"{row.costs.api_dollars:.2f}",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render(
    result: LoadResult,
    options: RuntimeOptions,
    rows: list[Aggregate],
    command: str,
    output_format: str,
    output: Path | None,
) -> None:
    if output_format == "json":
        text = render_json(result, options, rows, command)
    elif output_format == "csv":
        text = render_csv(rows)
    elif output_format == "markdown":
        text = render_markdown(rows)
    else:
        text = render_table(result, options, rows, f"Codex Meter - {command.title()}")
    write_output(text, output)
