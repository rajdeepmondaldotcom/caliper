from __future__ import annotations

import csv
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

from codex_meter.aggregation import aggregate_model_mode, aggregate_total
from codex_meter.humanize import format_int, redact
from codex_meter.models import Aggregate, CostTotals, LoadResult, RuntimeOptions, TokenTotals
from codex_meter.pricing import PRICING_SOURCES, RateCard
from codex_meter.timeutil import iso_z, window_label

__all__ = ["format_int", "redact", "render", "render_limits"]


def _rate_card(options: RuntimeOptions) -> RateCard:
    return RateCard.load(options.rates_file, options.pricing_mode)


def aggregate_to_dict(item: Aggregate, show_prompts: bool = False) -> dict:
    return {
        "key": item.key,
        "label": redact(item.label, show_prompts),
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
        "usage_sources": sorted(item.usage_sources),
        "model_context_window": item.model_context_window,
        "long_context_events": item.long_context_events,
        "unknown_model_events": item.unknown_model_events,
        "unknown_tier_events": item.unknown_tier_events,
    }


def rate_limit_sample_to_dict(sample) -> dict:
    item = asdict(sample)
    item["path"] = str(sample.path)
    item["timestamp"] = iso_z(sample.timestamp)
    return item


def report_payload(
    result: LoadResult,
    options: RuntimeOptions,
    rows: list[Aggregate],
    command: str,
    rate_card: RateCard | None = None,
) -> dict:
    card = rate_card or _rate_card(options)
    total = aggregate_total(result, options, rate_card=card)
    return {
        "command": command,
        "generated_at": iso_z(options.end),
        "window": {
            "start": iso_z(options.start),
            "end": iso_z(options.end),
            "label": window_label(options.start, options.end, options.timezone),
            "timezone": options.timezone,
        },
        "totals": aggregate_to_dict(total, options.show_prompts)
        | {"duplicates": result.duplicates},
        "breakdowns": [aggregate_to_dict(row, options.show_prompts) for row in rows],
        "model_mode": [
            aggregate_to_dict(row, options.show_prompts)
            for row in aggregate_model_mode(result, options, rate_card=card)
        ],
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
            "warning_count": len(result.warnings),
        },
        "rate_limit_samples": [
            rate_limit_sample_to_dict(sample) for sample in result.credit_samples
        ],
        "warnings": result.warnings,
    }


def write_output(text: str, output: Path | None) -> None:
    if output:
        output.expanduser().write_text(text)
    else:
        sys.stdout.write(text)


def render_table(
    result: LoadResult,
    options: RuntimeOptions,
    rows: list[Aggregate],
    title: str,
    rate_card: RateCard | None = None,
) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=100 if options.compact else None)
    total = aggregate_total(result, options, rate_card=rate_card or _rate_card(options))
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
    result: LoadResult,
    options: RuntimeOptions,
    rows: list[Aggregate],
    command: str,
    rate_card: RateCard | None = None,
) -> str:
    return (
        json.dumps(report_payload(result, options, rows, command, rate_card=rate_card), indent=2)
        + "\n"
    )


def render_csv(rows: list[Aggregate], show_prompts: bool) -> str:
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
        item = aggregate_to_dict(row, show_prompts)
        item["models"] = ",".join(item["models"])
        item["service_tiers"] = ",".join(item["service_tiers"])
        writer.writerow({key: item[key] for key in writer.fieldnames or []})
    return output.getvalue()


def render_markdown(rows: list[Aggregate], show_prompts: bool) -> str:
    headers = ["Group", "Events", "Input", "Cached", "Output", "Total", "Credits", "API $"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    totals = TokenTotals()
    costs = CostTotals()
    for row in rows:
        totals.events += row.totals.events
        totals.input_tokens += row.totals.input_tokens
        totals.cached_input_tokens += row.totals.cached_input_tokens
        totals.output_tokens += row.totals.output_tokens
        totals.total_tokens += row.totals.total_tokens
        costs.add(row.costs)
        lines.append(
            "| "
            + " | ".join(
                [
                    redact(row.label, show_prompts).replace("|", "\\|"),
                    str(row.totals.events),
                    str(row.totals.input_tokens),
                    str(row.totals.cached_input_tokens),
                    str(row.totals.output_tokens),
                    str(row.totals.total_tokens),
                    f"{row.costs.adjusted_credits:.2f}",
                    f"{row.costs.api_dollars:.2f}",
                ]
            )
            + " |"
        )
    if rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    "**Total**",
                    str(totals.events),
                    str(totals.input_tokens),
                    str(totals.cached_input_tokens),
                    str(totals.output_tokens),
                    str(totals.total_tokens),
                    f"{costs.adjusted_credits:.2f}",
                    f"{costs.api_dollars:.2f}",
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
    card = _rate_card(options)
    if output_format == "json":
        text = render_json(result, options, rows, command, rate_card=card)
    elif output_format == "csv":
        text = render_csv(rows, options.show_prompts)
    elif output_format == "markdown":
        text = render_markdown(rows, options.show_prompts)
    else:
        text = render_table(
            result, options, rows, f"Codex Meter - {command.title()}", rate_card=card
        )
    write_output(text, output)


LIMITS_CSV_FIELDS = (
    "timestamp",
    "session_id",
    "plan_type",
    "credits",
    "primary_used_percent",
    "primary_window_minutes",
    "primary_resets_at",
    "secondary_used_percent",
    "secondary_window_minutes",
    "secondary_resets_at",
    "rate_limit_reached_type",
)


def render_limits_table(result: LoadResult, options: RuntimeOptions) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=100 if options.compact else None)
    console.print("[bold]Codex Meter - Limits[/bold]")
    console.print(f"Window: {window_label(options.start, options.end, options.timezone)}")
    if not result.credit_samples:
        console.print("No rate-limit samples found.")
        return buffer.getvalue()
    for sample in result.credit_samples:
        console.print(
            f"- {iso_z(sample.timestamp)} | credits={sample.credits} | "
            f"primary={sample.primary_used_percent}%/"
            f"{sample.primary_window_minutes}m reset={sample.primary_resets_at} | "
            f"secondary={sample.secondary_used_percent}%/"
            f"{sample.secondary_window_minutes}m reset={sample.secondary_resets_at}"
        )
    return buffer.getvalue()


def render_limits_csv(result: LoadResult) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(LIMITS_CSV_FIELDS))
    writer.writeheader()
    for sample in result.credit_samples:
        row = rate_limit_sample_to_dict(sample)
        writer.writerow({key: row.get(key, "") for key in LIMITS_CSV_FIELDS})
    return out.getvalue()


def render_limits_markdown(result: LoadResult) -> str:
    headers = ["Timestamp", "Plan", "Credits", "Primary %", "Secondary %"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for sample in result.credit_samples:
        primary = sample.primary_used_percent
        secondary = sample.secondary_used_percent
        lines.append(
            "| "
            + " | ".join(
                [
                    iso_z(sample.timestamp),
                    str(sample.plan_type or ""),
                    str(sample.credits if sample.credits is not None else ""),
                    str(primary if primary is not None else ""),
                    str(secondary if secondary is not None else ""),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_limits(
    result: LoadResult,
    options: RuntimeOptions,
    output_format: str,
    output: Path | None,
) -> None:
    if output_format == "json":
        text = render_json(result, options, [], "limits", rate_card=_rate_card(options))
    elif output_format == "csv":
        text = render_limits_csv(result)
    elif output_format == "markdown":
        text = render_limits_markdown(result)
    else:
        text = render_limits_table(result, options)
    write_output(text, output)
