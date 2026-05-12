from __future__ import annotations

import csv
import datetime as dt
import io
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

from codex_meter.aggregation import aggregate_model_mode, aggregate_projects, aggregate_total
from codex_meter.humanize import compact_number, format_int, redact, short_table_label
from codex_meter.models import (
    Aggregate,
    CostTotals,
    LoadResult,
    RuntimeOptions,
    TokenTotals,
    decimal_string,
)
from codex_meter.pricing import PRICING_SOURCES, RateCard
from codex_meter.subscriptions import subscription_plan_payload, subscription_warnings
from codex_meter.timeutil import iso_z, window_label

__all__ = ["format_int", "redact", "render", "render_limits"]


def _rate_card(options: RuntimeOptions) -> RateCard:
    return RateCard.load(options.rates_file, options.pricing_mode)


def _make_console(buffer: io.StringIO, options: RuntimeOptions) -> Console:
    if options.width is not None:
        width = options.width
    elif options.compact:
        width = 100
    else:
        width = shutil.get_terminal_size((140, 24)).columns
    return Console(file=buffer, width=width, soft_wrap=False, _environ={})


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
        "credits": float(item.costs.adjusted_credits),
        "standard_credits": float(item.costs.standard_credits),
        "api_dollars": float(item.costs.api_dollars),
        "credits_exact": decimal_string(item.costs.adjusted_credits),
        "standard_credits_exact": decimal_string(item.costs.standard_credits),
        "api_dollars_exact": decimal_string(item.costs.api_dollars),
        "cache_savings_credits": float(item.cache_savings.adjusted_credits),
        "cache_savings_standard_credits": float(item.cache_savings.standard_credits),
        "cache_savings_api_dollars": float(item.cache_savings.api_dollars),
        "cache_savings_credits_exact": decimal_string(item.cache_savings.adjusted_credits),
        "cache_savings_standard_credits_exact": decimal_string(item.cache_savings.standard_credits),
        "cache_savings_api_dollars_exact": decimal_string(item.cache_savings.api_dollars),
        "models": sorted(item.models),
        "service_tiers": sorted(item.service_tiers),
        "plan_types": sorted(item.plan_types),
        "subscription_plans": subscription_plan_payload(item.plan_types),
        "usage_sources": sorted(item.usage_sources),
        "session_count": len(item.session_ids),
        "sessions": sorted(item.session_ids),
        "project_paths": sorted(item.project_paths),
        "project_names": sorted(item.project_names),
        "git_origins": sorted(item.git_origins),
        "git_branches": sorted(item.git_branches),
        "git_shas": sorted(item.git_shas),
        "agent_roles": sorted(item.agent_roles),
        "sources": sorted(item.sources),
        "first_seen": iso_z(item.first_seen) if item.first_seen else None,
        "last_seen": iso_z(item.last_seen) if item.last_seen else None,
        "model_context_window": item.model_context_window,
        "long_context_events": item.long_context_events,
        "unknown_model_events": item.unknown_model_events,
        "unknown_tier_events": item.unknown_tier_events,
        "pricing_status": pricing_status(item),
        "unpriced_events": item.costs.unpriced_events,
        "api_unpriced_events": item.costs.api_unpriced_events,
        "credit_unpriced_events": item.costs.credit_unpriced_events,
        "estimated_events": pricing_estimated_events(item),
        "ambiguous_reasoning_events": item.costs.ambiguous_reasoning_events,
        "local_rate_override_events": item.costs.local_override_events,
    }


def pricing_estimated_events(item: Aggregate) -> int:
    return (
        item.costs.estimated_events
        + item.unknown_tier_events
        + item.costs.ambiguous_reasoning_events
    )


def pricing_status(item: Aggregate) -> str:
    if item.costs.unpriced_events or item.unknown_model_events:
        return "partial"
    if pricing_estimated_events(item):
        return "estimated"
    return "exact"


def pricing_warnings(item: Aggregate) -> list[str]:
    warnings: list[str] = []
    if item.costs.api_unpriced_events:
        warnings.append(f"{item.costs.api_unpriced_events:,} events have no API-dollar rate.")
    if item.costs.credit_unpriced_events:
        warnings.append(f"{item.costs.credit_unpriced_events:,} events have no Codex credit rate.")
    if item.unknown_model_events:
        warnings.append(
            f"{item.unknown_model_events:,} events used models with no known rate card."
        )
    if item.unknown_tier_events:
        warnings.append(
            f"{item.unknown_tier_events:,} events used inferred service tiers; costs are estimates."
        )
    if item.costs.estimated_events:
        warnings.append(f"{item.costs.estimated_events:,} events used explicit estimate pricing.")
    if item.costs.ambiguous_reasoning_events:
        warnings.append(
            f"{item.costs.ambiguous_reasoning_events:,} events had ambiguous reasoning token shape."
        )
    return warnings


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
        "projects": [
            aggregate_to_dict(row, options.show_prompts)
            for row in aggregate_projects(result, options, rate_card=card)
        ],
        "model_mode": [
            aggregate_to_dict(row, options.show_prompts)
            for row in aggregate_model_mode(result, options, rate_card=card)
        ],
        "pricing": {
            "mode": options.pricing_mode,
            "offline": options.offline,
            "status": pricing_status(total),
            "warnings": pricing_warnings(total),
            "sources": [asdict(source) for source in PRICING_SOURCES],
        },
        "subscription": {
            "plans": subscription_plan_payload(total.plan_types),
            "warnings": subscription_warnings(total.plan_types),
        },
        "metadata": {
            "session_root": str(options.session_root),
            "state_db": str(options.state_db),
            "tier_sources": result.tier_sources,
            "plan_types": sorted(result.plan_types),
            "warning_count": len(result.warnings),
            "workspace_coverage": workspace_coverage(result),
        },
        "rate_limit_samples": [
            rate_limit_sample_to_dict(sample)
            for sample in _recent_samples(result.credit_samples, options.top_threads)
        ],
        "warnings": result.warnings,
    }


def workspace_coverage(result: LoadResult) -> dict:
    sessions = {event.session_id for event in result.events if event.session_id}
    sessions_with_project = {
        event.session_id for event in result.events if event.session_id and event.thread.cwd
    }
    project_paths = {event.thread.cwd for event in result.events if event.thread.cwd}
    events = len(result.events)
    events_with_project = sum(1 for event in result.events if event.thread.cwd)
    return {
        "events": events,
        "events_with_project": events_with_project,
        "event_coverage": events_with_project / events if events else 0.0,
        "sessions": len(sessions),
        "sessions_with_project": len(sessions_with_project),
        "session_coverage": len(sessions_with_project) / len(sessions) if sessions else 0.0,
        "project_count": len(project_paths),
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
    console = _make_console(buffer, options)
    total = aggregate_total(result, options, rate_card=rate_card or _rate_card(options))
    console.print(f"[bold]{title}[/bold]")
    console.print(f"Window: {window_label(options.start, options.end, options.timezone)}")
    console.print(f"Session root: {options.session_root}")
    if result.warnings:
        for warning in result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
    for warning in pricing_warnings(total):
        console.print(
            f"[yellow]Warning:[/yellow] {warning} Reported costs are {pricing_status(total)}."
        )
    for warning in subscription_warnings(total.plan_types):
        console.print(f"[yellow]Subscription:[/yellow] {warning}")
    console.print()

    table = Table(show_lines=False, expand=not options.compact)
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
            short_table_label(redact(row.label, options.show_prompts)),
            "\n".join(sorted(row.models)) or "-",
            _table_int(row.totals.input_tokens, options),
            _table_int(row.totals.cached_input_tokens, options),
            _table_int(row.totals.output_tokens, options),
            _table_int(row.totals.total_tokens, options),
            _table_float(row.costs.adjusted_credits, options),
            _table_float(row.costs.api_dollars, options, prefix="$"),
        )
    table.add_section()
    table.add_row(
        "Total",
        "\n".join(sorted(total.models)) or "-",
        _table_int(total.totals.input_tokens, options),
        _table_int(total.totals.cached_input_tokens, options),
        _table_int(total.totals.output_tokens, options),
        _table_int(total.totals.total_tokens, options),
        _table_float(total.costs.adjusted_credits, options),
        _table_float(total.costs.api_dollars, options, prefix="$"),
    )
    console.print(table)
    console.print()
    events_text = format_int(total.totals.events)
    duplicates_text = format_int(result.duplicates)
    console.print(f"Events: {events_text} | Duplicates skipped: {duplicates_text}")
    if total.costs.adjusted_credits != total.costs.standard_credits:
        console.print(f"Standard-mode baseline: {total.costs.standard_credits:,.2f} credits")
    if total.cache_savings.adjusted_credits or total.cache_savings.api_dollars:
        console.print(
            "Cache savings: "
            f"{total.cache_savings.adjusted_credits:,.2f} credits | "
            f"${total.cache_savings.api_dollars:,.2f}"
        )
    if result.tier_sources:
        sources = ", ".join(
            f"{key}={format_int(value)}" for key, value in sorted(result.tier_sources.items())
        )
        console.print(f"Service-tier sources: {sources}")
    if result.plan_types:
        console.print(f"Plan types: {', '.join(sorted(result.plan_types))}")
    return buffer.getvalue()


def _table_int(value: int, options: RuntimeOptions) -> str:
    return compact_number(value) if options.compact else format_int(value)


def _table_float(value: float, options: RuntimeOptions, prefix: str = "") -> str:
    if options.compact:
        return compact_number(value, prefix=prefix)
    if prefix:
        return f"{prefix}{value:,.2f}"
    return f"{value:,.2f}"


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
            "pricing_status",
            "unpriced_events",
            "estimated_events",
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
    headers = [
        "Group",
        "Events",
        "Input",
        "Cached",
        "Output",
        "Total",
        "Credits",
        "API $",
        "Pricing",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    totals = TokenTotals()
    costs = CostTotals()
    row_statuses: set[str] = set()
    for row in rows:
        row_statuses.add(pricing_status(row))
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
                    pricing_status(row),
                ]
            )
            + " |"
        )
    if rows:
        total_status = (
            "partial"
            if "partial" in row_statuses
            else "estimated"
            if "estimated" in row_statuses
            else "exact"
        )
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
                    total_status,
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
    "limit_id",
    "limit_name",
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
    console = _make_console(buffer, options)
    console.print("[bold]Codex Meter - Limits[/bold]")
    console.print(f"Window: {window_label(options.start, options.end, options.timezone)}")
    samples = _recent_samples(result.credit_samples, options.top_threads)
    if not samples:
        console.print("No rate-limit samples found.")
        return buffer.getvalue()
    if options.compact:
        for sample in samples:
            limit = sample.limit_name or sample.limit_id or "-"
            console.print(
                f"- {iso_z(sample.timestamp)} | limit={limit} | credits={sample.credits} | "
                f"primary={sample.primary_used_percent}%/"
                f"{sample.primary_window_minutes}m reset={sample.primary_resets_at} | "
                f"secondary={sample.secondary_used_percent}%/"
                f"{sample.secondary_window_minutes}m reset={sample.secondary_resets_at}"
            )
        return buffer.getvalue()
    table = Table(show_lines=False, expand=not options.compact)
    table.add_column("Time")
    table.add_column("Limit")
    table.add_column("Plan")
    table.add_column("Credits", justify="right")
    table.add_column("Primary %", justify="right")
    table.add_column("Reset In", justify="right")
    table.add_column("Secondary %", justify="right")
    table.add_column("Reset In", justify="right")
    for sample in samples:
        table.add_row(
            iso_z(sample.timestamp),
            sample.limit_name or sample.limit_id or "-",
            str(sample.plan_type or "-"),
            str(sample.credits if sample.credits is not None else "-"),
            _percent(sample.primary_used_percent),
            _reset_epoch(sample.primary_resets_at),
            _percent(sample.secondary_used_percent),
            _reset_epoch(sample.secondary_resets_at),
        )
    console.print(table)
    return buffer.getvalue()


def _percent(value: object) -> str:
    return "-" if value is None else f"{float(value):.1f}%"


def _reset_epoch(value: object) -> str:
    if value in {None, ""}:
        return "-"
    try:
        reset_at = dt.datetime.fromtimestamp(float(value), tz=dt.UTC)
    except (TypeError, ValueError, OSError):
        return str(value)
    remaining = reset_at - dt.datetime.now(tz=dt.UTC)
    seconds = int(remaining.total_seconds())
    if seconds <= 0:
        return "now"
    minutes, leftover = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {leftover}s"


def _recent_samples(samples: list, limit: int) -> list:
    return sorted(samples, key=lambda sample: sample.timestamp)[-limit:]


def render_limits_csv(result: LoadResult, options: RuntimeOptions) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(LIMITS_CSV_FIELDS))
    writer.writeheader()
    for sample in _recent_samples(result.credit_samples, options.top_threads):
        row = rate_limit_sample_to_dict(sample)
        writer.writerow({key: row.get(key, "") for key in LIMITS_CSV_FIELDS})
    return out.getvalue()


def render_limits_markdown(result: LoadResult, options: RuntimeOptions) -> str:
    headers = ["Timestamp", "Limit", "Plan", "Credits", "Primary %", "Secondary %"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for sample in _recent_samples(result.credit_samples, options.top_threads):
        primary = sample.primary_used_percent
        secondary = sample.secondary_used_percent
        lines.append(
            "| "
            + " | ".join(
                [
                    iso_z(sample.timestamp),
                    sample.limit_name or sample.limit_id or "",
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
        text = render_limits_csv(result, options)
    elif output_format == "markdown":
        text = render_limits_markdown(result, options)
    else:
        text = render_limits_table(result, options)
    write_output(text, output)
