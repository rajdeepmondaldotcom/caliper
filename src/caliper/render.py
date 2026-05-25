from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import shutil
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from caliper import SCHEMA_VERSION, __version__
from caliper.aggregation import aggregate_many, aggregate_total, budget_impact_sort_key
from caliper.evidence import (
    evidence_dimensions,
    evidence_metadata,
    parser_issue_warning,
    worst_grade,
)
from caliper.humanize import compact_number, format_int, redact, short_table_label
from caliper.models import (
    UNKNOWN_PROJECT,
    Aggregate,
    CostTotals,
    LoadResult,
    ModelBreakdown,
    RuntimeOptions,
    TokenTotals,
    decimal_string,
    decimal_value,
)
from caliper.pricing import PRICING_SOURCES, RateCard, load_rate_card, pricing_catalog_status
from caliper.subscriptions import (
    subscription_cost_caveat,
    subscription_plan_payload,
    subscription_warnings,
)
from caliper.timeutil import iso_z, window_label

__all__ = ["format_int", "redact", "render", "render_limits"]


def _rate_card(options: RuntimeOptions) -> RateCard:
    return load_rate_card(options)


def _make_console(buffer: io.StringIO, options: RuntimeOptions) -> Console:
    if options.width is not None:
        width = options.width
    elif options.compact:
        width = 100
    else:
        width = shutil.get_terminal_size((140, 24)).columns
    return Console(file=buffer, width=width, soft_wrap=False, _environ={})


def aggregate_to_dict(item: Aggregate, show_prompts: bool = False) -> dict:
    reported = item.costs.reported_cost_usd if item.costs.vendor_reported_events else None
    payload = {
        "key": item.key,
        "label": redact(item.label, show_prompts),
        "events": item.totals.events,
        "input_tokens": item.totals.input_tokens,
        "cache_creation_input_tokens": item.totals.cache_creation_input_tokens,
        "cache_read_input_tokens": item.totals.cache_read_input_tokens,
        "cache_creation_input_1h_tokens": item.totals.cache_creation_input_1h_tokens,
        "cached_input_tokens": item.totals.cached_input_tokens,
        "uncached_input_tokens": item.totals.uncached_input_tokens,
        "output_tokens": item.totals.output_tokens,
        "reasoning_output_tokens": item.totals.reasoning_output_tokens,
        "total_tokens": item.totals.total_tokens,
        "cost_usd": float(item.costs.cost_usd),
        "reported_cost_usd": float(reported) if reported is not None else None,
        "calculated_cost_usd": float(item.costs.calculated_cost_usd),
        "reported_minus_calculated_cost_usd": float(item.costs.reported_calculated_delta_usd),
        "cost_usd_exact": decimal_string(item.costs.cost_usd),
        "reported_cost_usd_exact": decimal_string(reported) if reported is not None else None,
        "calculated_cost_usd_exact": decimal_string(item.costs.calculated_cost_usd),
        "reported_minus_calculated_cost_usd_exact": decimal_string(
            item.costs.reported_calculated_delta_usd
        ),
        "cache_savings_cost_usd": float(item.cache_savings.cost_usd),
        "cache_savings_cost_usd_exact": decimal_string(item.cache_savings.cost_usd),
        "models": sorted(item.models),
        "model_vendors": sorted(item.model_vendors),
        "vendors": sorted(item.vendors),
        "service_tiers": sorted(item.service_tiers),
        "plan_types": sorted(item.plan_types),
        "subscription_plans": subscription_plan_payload(item.plan_types),
        "usage_sources": sorted(item.usage_sources),
        "model_sources": sorted(item.model_sources),
        "fallback_model_events": item.fallback_model_events,
        "model_breakdowns": [model_breakdown_to_dict(row) for row in sorted_model_breakdowns(item)],
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
        "estimated_events": pricing_estimated_events(item),
        "ambiguous_reasoning_events": item.costs.ambiguous_reasoning_events,
        "local_rate_override_events": item.costs.local_override_events,
        "vendor_reported_events": item.costs.vendor_reported_events,
    }
    if item.key in item.session_ids:
        payload["session"] = item.label
    return payload


def sorted_model_breakdowns(item: Aggregate) -> list[ModelBreakdown]:
    return sorted(
        item.model_breakdowns.values(),
        key=lambda row: (
            -row.costs.cost_usd,
            -row.totals.events,
            row.model,
            row.service_tier,
        ),
    )


def model_breakdown_to_dict(item: ModelBreakdown) -> dict:
    reported = item.costs.reported_cost_usd if item.costs.vendor_reported_events else None
    return {
        "key": item.key,
        "model": item.model,
        "model_vendor": item.model_vendor,
        "service_tier": item.service_tier,
        "events": item.totals.events,
        "input_tokens": item.totals.input_tokens,
        "cache_creation_input_tokens": item.totals.cache_creation_input_tokens,
        "cache_read_input_tokens": item.totals.cache_read_input_tokens,
        "cache_creation_input_1h_tokens": item.totals.cache_creation_input_1h_tokens,
        "cached_input_tokens": item.totals.cached_input_tokens,
        "uncached_input_tokens": item.totals.uncached_input_tokens,
        "output_tokens": item.totals.output_tokens,
        "reasoning_output_tokens": item.totals.reasoning_output_tokens,
        "total_tokens": item.totals.total_tokens,
        "cost_usd": float(item.costs.cost_usd),
        "reported_cost_usd": float(reported) if reported is not None else None,
        "calculated_cost_usd": float(item.costs.calculated_cost_usd),
        "reported_minus_calculated_cost_usd": float(item.costs.reported_calculated_delta_usd),
        "cost_usd_exact": decimal_string(item.costs.cost_usd),
        "reported_cost_usd_exact": decimal_string(reported) if reported is not None else None,
        "calculated_cost_usd_exact": decimal_string(item.costs.calculated_cost_usd),
        "reported_minus_calculated_cost_usd_exact": decimal_string(
            item.costs.reported_calculated_delta_usd
        ),
        "cache_savings_cost_usd": float(item.cache_savings.cost_usd),
        "cache_savings_cost_usd_exact": decimal_string(item.cache_savings.cost_usd),
        "plan_types": sorted(item.plan_types),
        "usage_sources": sorted(item.usage_sources),
        "model_sources": sorted(item.model_sources),
        "long_context_events": item.long_context_events,
        "unknown_model_events": item.unknown_model_events,
        "unknown_tier_events": item.unknown_tier_events,
        "fallback_model_events": item.fallback_model_events,
        "pricing_status": model_breakdown_pricing_status(item),
        "unpriced_events": item.costs.unpriced_events,
        "estimated_events": model_breakdown_estimated_events(item),
        "ambiguous_reasoning_events": item.costs.ambiguous_reasoning_events,
        "local_rate_override_events": item.costs.local_override_events,
        "vendor_reported_events": item.costs.vendor_reported_events,
        "first_seen": iso_z(item.first_seen) if item.first_seen else None,
        "last_seen": iso_z(item.last_seen) if item.last_seen else None,
    }


def model_breakdown_estimated_events(item: ModelBreakdown) -> int:
    return (
        item.costs.estimated_events
        + item.unknown_tier_events
        + item.costs.ambiguous_reasoning_events
        + item.fallback_model_events
    )


def model_breakdown_pricing_status(item: ModelBreakdown) -> str:
    if item.costs.unpriced_events > item.costs.vendor_reported_events:
        return "partial"
    if item.unknown_model_events > item.costs.vendor_reported_events:
        return "partial"
    if model_breakdown_estimated_events(item):
        return "estimated"
    if item.costs.vendor_reported_events:
        return "vendor-reported"
    return "exact"


def pricing_estimated_events(item: Aggregate) -> int:
    return (
        item.costs.estimated_events
        + item.unknown_tier_events
        + item.costs.ambiguous_reasoning_events
        + item.fallback_model_events
    )


def pricing_status(item: Aggregate) -> str:
    if item.costs.unpriced_events > item.costs.vendor_reported_events:
        return "partial"
    if item.unknown_model_events > item.costs.vendor_reported_events:
        return "partial"
    if pricing_estimated_events(item):
        return "estimated"
    if item.costs.vendor_reported_events:
        return "vendor-reported"
    return "exact"


def pricing_warnings(item: Aggregate) -> list[str]:
    warnings: list[str] = []
    if item.costs.unpriced_events:
        if item.costs.vendor_reported_events:
            warnings.append(
                f"{item.costs.unpriced_events:,} events could not be independently "
                "calculated from the local USD rate card."
            )
        else:
            warnings.append(f"{item.costs.unpriced_events:,} events have no USD rate.")
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
    if item.fallback_model_events:
        warnings.append(
            f"{item.fallback_model_events:,} events used the configured default model because "
            "no model was recorded."
        )
    return warnings


def pricing_is_material(item: Aggregate) -> bool:
    """True when the unpriced gap is large enough (> 5% of events) to merit a
    warning rather than a calm note. A handful of unpriced events out of tens
    of thousands should not read like a data emergency."""
    events = item.totals.events or 0
    if not events:
        return bool(item.costs.unpriced_events)
    return item.costs.unpriced_events / events > 0.05


def pricing_summary_line(item: Aggregate) -> str | None:
    """One concise evidence caveat in place of a stack of per-category
    warnings. The per-category detail still ships in the JSON envelope and is
    available via ``caliper evidence`` / ``caliper doctor``; the header only
    needs to tell a reader how complete the totals are and where to look."""
    if not pricing_warnings(item):
        return None
    status = pricing_status(item)
    events = item.totals.events or 0
    unpriced = item.costs.unpriced_events
    if unpriced and events:
        pct = unpriced / events
        return (
            f"Cost evidence is {status} — {unpriced:,} of {events:,} events "
            f"({pct:.1%}) are unpriced, so cost totals are ~{1 - pct:.1%} complete. "
            "Run `caliper evidence` for the breakdown."
        )
    estimated = pricing_estimated_events(item)
    if estimated and events:
        pct = estimated / events
        return (
            f"Cost evidence is {status} — {estimated:,} of {events:,} events "
            f"({pct:.1%}) use estimated or inferred pricing. "
            "Run `caliper evidence` for the breakdown."
        )
    return f"Cost evidence is {status}. Run `caliper evidence` for the breakdown."


def rate_limit_sample_to_dict(sample) -> dict:
    item = asdict(sample)
    item["path"] = str(sample.path)
    item["timestamp"] = iso_z(sample.timestamp)
    return item


_IDENTITY_REDACTION_MARKERS = {
    "session_id": "<redacted-session>",
    "sessions": "<redacted-session>",
    "git_origin": "<redacted-repo>",
    "git_origins": "<redacted-repo>",
    "git_origin_url": "<redacted-repo>",
    "git_sha": "<redacted-git-sha>",
    "git_shas": "<redacted-git-sha>",
    "git_branch": "<redacted-git-branch>",
    "git_branches": "<redacted-git-branch>",
}


def _redact_paths(payload: Any, options: RuntimeOptions, key: str | None = None) -> Any:
    """Remove local paths and repo/session identity from default machine-readable output."""
    if options.show_paths:
        return payload
    marker = _IDENTITY_REDACTION_MARKERS.get(key or "")
    if marker:
        return _redact_identity(payload, marker)
    if key == "path":
        return _redact_path_identity(payload, options)
    if isinstance(payload, dict):
        return {
            item_key: _redact_paths(value, options, str(item_key))
            for item_key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_redact_paths(value, options, key) for value in payload]
    if isinstance(payload, tuple):
        return tuple(_redact_paths(value, options, key) for value in payload)
    if isinstance(payload, str):
        return _redact_path_string(payload, options)
    return payload


def _redact_identity(value: Any, marker: str) -> Any:
    if isinstance(value, list):
        return [_redact_identity(item, marker) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_identity(item, marker) for item in value)
    if isinstance(value, str):
        return marker if value else value
    return value


def _redact_path_identity(value: Any, options: RuntimeOptions) -> Any:
    if isinstance(value, list):
        return [_redact_path_identity(item, options) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_path_identity(item, options) for item in value)
    if isinstance(value, str):
        redacted = _redact_path_string(value, options)
        return "<redacted-path>" if redacted != value else redacted
    return value


def _redact_path_string(value: str, options: RuntimeOptions) -> str:
    if "://" in value:
        return value
    roots = {
        Path.home(),
        options.session_root,
        options.session_root.parent,
        options.state_db,
        options.state_db.parent,
        options.config_path,
        options.config_path.parent,
    }
    redacted = value
    root_strings: set[str] = set()
    for path in roots:
        expanded = path.expanduser()
        text = str(expanded)
        if not text or text == "." or text == expanded.anchor:
            continue
        root_strings.add(text)
    for root in sorted(root_strings, key=len, reverse=True):
        if root and root in redacted:
            redacted = redacted.replace(root, "<redacted-path>")
    redacted = _redact_encoded_absolute_path_segments(redacted)
    if redacted != value:
        return redacted
    if value.startswith("/"):
        return "<redacted-path>"
    return re.sub(r"(?<![:\w])/(?:[^\s;,)]+)", "<redacted-path>", value)


def _redact_encoded_absolute_path_segments(value: str) -> str:
    """Redact path fragments encoded into vendor directory names.

    Cursor and Claude Code can encode project paths as a single path segment,
    for example ``Users-name-Documents-repo``. Absolute-path replacement does
    not catch those because there is no slash left to match.
    """

    encoded_absolute_roots = r"(?:[A-Za-z][-_])?[-_]?(?:Users|home|private[-_]var|tmp)[-_]"
    segment = rf"(^|[/\\]){encoded_absolute_roots}[^/\\\s,;)]+"
    return re.sub(segment, r"\1<redacted-path>", value)


def report_payload(
    result: LoadResult,
    options: RuntimeOptions,
    rows: list[Aggregate],
    command: str,
    rate_card: RateCard | None = None,
) -> dict:
    card = rate_card or _rate_card(options)
    total_rows, project_rows, model_mode_rows = aggregate_many(
        result.events,
        [_total_key, _project_key, _model_mode_key],
        options,
        rate_card=card,
    )
    total = total_rows[0] if total_rows else Aggregate(key="total", label="Total")
    projects = sorted(project_rows, key=budget_impact_sort_key)
    model_mode = sorted(model_mode_rows, key=budget_impact_sort_key)
    samples = _report_rate_limit_samples(result.rate_limit_samples, options)
    _subscription_caveat = subscription_cost_caveat(total.plan_types)
    payload = {
        "caliper": {
            "version": __version__,
            "schema_version": SCHEMA_VERSION,
        },
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
        "projects": [aggregate_to_dict(row, options.show_prompts) for row in projects],
        "model_mode": [aggregate_to_dict(row, options.show_prompts) for row in model_mode],
        "pricing": {
            "mode": options.pricing_mode,
            "source": options.pricing_source,
            "offline": options.offline,
            "status": pricing_status(total),
            "warnings": pricing_warnings(total),
            "catalog": pricing_catalog_status(card),
            "sources": [asdict(source) for source in PRICING_SOURCES],
        },
        "subscription": {
            "plans": subscription_plan_payload(total.plan_types),
            "warnings": subscription_warnings(total.plan_types),
            "cost_basis": "api-equivalent" if _subscription_caveat else "billed",
            "cost_caveat": _subscription_caveat,
        },
        "metadata": {
            "session_root": str(options.session_root),
            "state_db": str(options.state_db),
            "tier_sources": result.tier_sources,
            "model_sources": model_source_counts(result),
            "plan_types": sorted(result.plan_types),
            "warning_count": len(result.warnings),
            "workspace_coverage": workspace_coverage(result),
            "vendor_event_counts": vendor_event_counts(result),
            "dedupe": {
                "duplicates": result.duplicates,
                "usage_event_duplicates": result.duplicates,
                "by_strategy": dict(result.dedupe_stats),
                "rate_limit_sample_duplicates": result.rate_limit_sample_duplicates,
                "rate_limit_samples_by_strategy": dict(result.rate_limit_sample_dedupe_stats),
            },
            "evidence": evidence_metadata(result, total),
            "row_count": len(rows),
            "row_limit": options.top_threads,
            "rows_truncated": bool(options.top_threads and len(rows) >= options.top_threads),
            "rate_limit_sample_count": len(result.rate_limit_samples),
            "rate_limit_sample_limit": None
            if options.include_all_rate_limit_samples
            else options.rate_limit_sample_limit,
            "rate_limit_samples_truncated": len(samples) < len(result.rate_limit_samples),
            "path_redaction": "visible" if options.show_paths else "redacted",
        },
        "rate_limit_samples": [rate_limit_sample_to_dict(sample) for sample in samples],
        "warnings": result.warnings,
    }
    return _redact_paths(payload, options)


def _total_key(_event) -> tuple[str, str]:
    return "total", "Total"


def _project_key(event) -> tuple[str, str]:
    project = event.thread.cwd or UNKNOWN_PROJECT
    return project, project


def _model_mode_key(event) -> tuple[str, str]:
    return (
        f"{event.model}\0{event.service_tier}",
        f"{event.model or 'unknown model'} / {event.service_tier or 'unknown tier'}",
    )


def vendor_event_counts(result: LoadResult) -> dict[str, int]:
    """Return {vendor_id: event_count} for events loaded across vendors."""
    counts: dict[str, int] = {}
    for event in result.events:
        vendor = event.vendor or "unknown"
        counts[vendor] = counts.get(vendor, 0) + 1
    return counts


def model_source_counts(result: LoadResult) -> dict[str, int]:
    """Return {model_source: event_count} for loaded events."""
    counts: dict[str, int] = {}
    for event in result.events:
        source = event.model_source or "unknown"
        counts[source] = counts.get(source, 0) + 1
    return counts


def _vendor_breakdown(result: LoadResult) -> str:
    counts = vendor_event_counts(result)
    if not counts:
        return ""
    parts = [f"{vendor} ({format_int(count)} events)" for vendor, count in sorted(counts.items())]
    return " · ".join(parts)


def workspace_coverage(result: LoadResult) -> dict:
    events = len(result.events)
    events_with_project = sum(1 for event in result.events if event.thread.cwd)
    sessions = _session_ids(result.events)
    sessions_with_project = _session_ids_with_project(result.events)
    return {
        "events": events,
        "events_with_project": events_with_project,
        "event_coverage": events_with_project / events if events else 0.0,
        "sessions": len(sessions),
        "sessions_with_project": len(sessions_with_project),
        "session_coverage": len(sessions_with_project) / len(sessions) if sessions else 0.0,
        "project_count": len(_project_paths(result.events)),
    }


def _session_ids(events) -> set[str]:
    return {event.session_id for event in events if event.session_id}


def _session_ids_with_project(events) -> set[str]:
    return {event.session_id for event in events if event.session_id and event.thread.cwd}


def _project_paths(events) -> set[str]:
    return {event.thread.cwd for event in events if event.thread.cwd}


def write_output(text: str, output: Path | None) -> None:
    if output:
        path = output.expanduser()
        # Create missing parent dirs so `--output some/new/dir/file.json`
        # works instead of raising FileNotFoundError. An unwritable target
        # (a directory, a read-only path) surfaces a one-line error instead
        # of a raw traceback. Mirrors the CLI's _write_output_file helper.
        try:
            if path.parent and not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            import typer
            from rich.markup import escape

            Console().print(
                f"[red]error:[/red] could not write {escape(str(path))}: "
                f"{escape(exc.strerror or str(exc))}"
            )
            raise typer.Exit(2) from exc
        return
    import contextlib

    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:
        # `caliper daily --format json | head` is a real usage pattern.
        # Swallow the broken pipe and exit clean. Mirrors the pattern in
        # most POSIX line-oriented tools.
        with contextlib.suppress(BrokenPipeError):
            sys.stdout.close()


def render_table(
    result: LoadResult,
    options: RuntimeOptions,
    rows: list[Aggregate],
    title: str,
    rate_card: RateCard | None = None,
    total: Aggregate | None = None,
) -> str:
    buffer = io.StringIO()
    console = _make_console(buffer, options)
    total = total or aggregate_total(result, options, rate_card=rate_card or _rate_card(options))
    if title == "Caliper - Overview" and total.totals.events == 0:
        _print_no_data_overview(console, options)
        return buffer.getvalue()
    _print_report_header(console, result, options, title, total)
    console.print(_usage_table(rows, total, options))
    console.print()
    _print_report_footer(console, result, total)
    return buffer.getvalue()


def _print_no_data_overview(console: Console, options: RuntimeOptions) -> None:
    from caliper.vendors import vendor_summaries

    console.print("[bold]Caliper - Overview[/bold]")
    console.print("No AI coding usage logs found in the active window.")
    console.print()
    console.print("Checked:")
    for summary in vendor_summaries(options):
        if not summary.enabled:
            continue
        count = f"{summary.files:,} files" if summary.files else "no files found"
        console.print(f"- {summary.label}: {count}")
    if options.show_paths:
        console.print(f"- OpenAI Codex sessions path: {options.session_root}")
        console.print(f"- OpenAI Codex state DB path: {options.state_db}")
    console.print()
    console.print("Next:")
    console.print("- Run `caliper doctor` to inspect local setup.")
    console.print("- Run `caliper tui --demo` to explore Caliper with sample data.")


def _print_report_header(
    console: Console,
    result: LoadResult,
    options: RuntimeOptions,
    title: str,
    total: Aggregate,
) -> None:
    console.print(f"[bold]{title}[/bold]")
    console.print(f"Window: {window_label(options.start, options.end, options.timezone)}")
    _print_data_source(console, result, options)
    vendor_breakdown = _vendor_breakdown(result)
    if vendor_breakdown:
        console.print(f"Vendors: {vendor_breakdown}")
    if result.warnings:
        # Coverage caveats (e.g. "Cursor files have no per-event token counts")
        # repeat on every analytical command and quickly become noise. Collapse
        # them to one short pointer here; the full detail still lives in the JSON
        # envelope, `caliper doctor`, and `caliper evidence`, which read
        # ``result.parser_issues`` directly rather than this header.
        coverage_warnings = {
            parser_issue_warning(issue)
            for issue in result.parser_issues
            if issue.kind.startswith("unsupported:")
        }
        saw_coverage = False
        for warning in result.warnings:
            if warning in coverage_warnings:
                saw_coverage = True
                continue
            console.print(f"[yellow]Warning:[/yellow] {warning}")
        if saw_coverage:
            console.print(
                "[yellow]Note:[/yellow] Some sources have limited token coverage. "
                "Run `caliper doctor` for details."
            )
    summary = pricing_summary_line(total)
    if summary:
        label = "Warning" if pricing_is_material(total) else "Note"
        console.print(f"[yellow]{label}:[/yellow] {summary}")
    for warning in subscription_warnings(total.plan_types):
        console.print(f"[yellow]Subscription:[/yellow] {warning}")
    caveat = subscription_cost_caveat(total.plan_types)
    if caveat:
        console.print(f"[yellow]Subscription:[/yellow] {caveat}")
    console.print()


def _print_data_source(console: Console, result: LoadResult, options: RuntimeOptions) -> None:
    vendor = _single_tool_vendor(result)
    if vendor in {None, "", "openai-codex"}:
        console.print(f"Session root: {_human_path(options.session_root, options)}")
        return
    labels = {
        "claude-code": "Claude Code local logs",
        "cursor": "Cursor local data",
        "aider": "Aider chat histories",
    }
    console.print(f"Data source: {labels.get(vendor, vendor)}")


def _human_path(path: Path, options: RuntimeOptions) -> str:
    if options.show_paths:
        return str(path)
    return _redact_path_string(str(path), options)


def _single_tool_vendor(result: LoadResult) -> str | None:
    vendors = {event.vendor for event in result.events if event.vendor}
    if len(vendors) == 1:
        return next(iter(vendors))
    return None


def _usage_table(rows: list[Aggregate], total: Aggregate, options: RuntimeOptions) -> Table:
    if _uses_narrow_table(options):
        return _narrow_usage_table(rows, total, options)

    table = Table(show_lines=False, expand=not options.compact)
    table.add_column("Group")
    table.add_column("Models", overflow="fold", max_width=42)
    table.add_column("Input", justify="right")
    table.add_column("Cached", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Cost $", justify="right")
    # "Reported $" (vendor-stated) and "Calc $" (independently computed) only
    # carry information when some events actually ship a vendor cost. For
    # log-only sources (Claude Code, Codex) they are always "-" and identical
    # to "Cost $", so collapse to a single column rather than show two dead ones.
    show_split = total.costs.vendor_reported_events > 0
    if show_split:
        table.add_column("Reported $", justify="right")
        table.add_column("Calc $", justify="right")

    def _row_cells(item: Aggregate, label: str) -> list[str]:
        cells = [
            label,
            compact_models(item),
            _table_int(item.totals.input_tokens, options),
            _table_int(item.totals.cached_input_tokens, options),
            _table_int(item.totals.output_tokens, options),
            _table_int(item.totals.total_tokens, options),
            _cost_cell(item.costs, options),
        ]
        if show_split:
            cells.append(_reported_cost(item.costs, options))
            cells.append(_calculated_cost(item.costs, options))
        return cells

    for row in rows:
        table.add_row(*_row_cells(row, short_table_label(redact(row.label, options.show_prompts))))
    table.add_section()
    table.add_row(*_row_cells(total, "Total"))
    return table


def _uses_narrow_table(options: RuntimeOptions) -> bool:
    width = options.width
    if width is None:
        width = 100 if options.compact else shutil.get_terminal_size((140, 24)).columns
    return options.compact or width < 100


def _narrow_usage_table(rows: list[Aggregate], total: Aggregate, options: RuntimeOptions) -> Table:
    table = Table(show_lines=False, expand=False)
    table.add_column("Group", overflow="ellipsis", no_wrap=True, max_width=28)
    table.add_column("Tokens", justify="right", no_wrap=True, width=10)
    table.add_column("Cost", justify="right", no_wrap=True, width=10)
    table.add_column("Pricing", overflow="ellipsis", no_wrap=True, max_width=16)
    for row in rows:
        table.add_row(
            short_table_label(redact(row.label, options.show_prompts)),
            _table_int(row.totals.total_tokens, options),
            _cost_cell(row.costs, options),
            pricing_status(row),
        )
    table.add_section()
    table.add_row(
        "Total",
        _table_int(total.totals.total_tokens, options),
        _cost_cell(total.costs, options),
        pricing_status(total),
    )
    return table


_MODEL_PREFIX_DROP = ("claude-", "openai-", "gpt-")


def short_model(name: str) -> str:
    """Strip well-known vendor prefixes so model cells stay scannable."""
    lowered = name.lower()
    if lowered.startswith("gpt-"):
        return name  # GPT-N is already short
    for prefix in _MODEL_PREFIX_DROP:
        if lowered.startswith(prefix):
            return name[len(prefix) :]
    return name


def compact_models(row: Aggregate, limit: int = 3) -> str:
    """Render the top models on line 1 and the vendor chip on line 2.

    Returns the top ``limit`` model breakdowns sorted by spend (API
    dollars desc), with a "+N" suffix when there are extras. Falls back
    to alphabetical when per-model costs are unavailable. Vendor
    prefixes (``claude-``, ``openai-``) are stripped from model names
    so the cell fits a typical 40-column report layout. Beneath that
    line a dim chip lists the distinct model vendors present in the
    row (e.g. ``Anthropic · OpenAI``). Use :func:`compact_models_oneline`
    when the caller wants the single-line variant.
    """
    one_line = compact_models_oneline(row, limit=limit)
    chip = vendor_chip(row)
    if not chip:
        return one_line
    return f"{one_line}\n[dim]{chip}[/dim]"


def compact_models_oneline(row: Aggregate, limit: int = 3) -> str:
    """The historical single-line form. Kept for JSON, CSV, and tests."""
    if not row.models:
        return "-"
    ranked = _rank_models(row)
    if not ranked:
        ranked = sorted(row.models)
    head = [short_model(name) for name in ranked[:limit]]
    remaining = len(ranked) - len(head)
    suffix = f" +{remaining}" if remaining > 0 else ""
    return " · ".join(head) + suffix


_VENDOR_LABELS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "anysphere": "Anysphere",
    "google": "Google",
    "mistral": "Mistral",
    "meta": "Meta",
    "unknown": "unknown",
}


def vendor_chip(row: Aggregate) -> str:
    """Return a comma-free vendor chip for the row, sorted by spend.

    Falls back to the alphabetical model-vendor set when per-breakdown
    spend is not available. Returns an empty string when no vendor
    information exists.
    """
    breakdowns = getattr(row, "model_breakdowns", None) or {}
    if breakdowns:
        ordered: list[str] = []
        seen: set[str] = set()
        for breakdown in sorted(
            breakdowns.values(),
            key=lambda mb: mb.costs.cost_usd,
            reverse=True,
        ):
            vendor = getattr(breakdown, "model_vendor", "unknown") or "unknown"
            if vendor in seen:
                continue
            seen.add(vendor)
            ordered.append(vendor)
        vendors = ordered
    else:
        vendors = sorted(getattr(row, "model_vendors", set()) or set())
    if not vendors:
        return ""
    return " · ".join(_VENDOR_LABELS.get(v, v) for v in vendors)


def _rank_models(row: Aggregate) -> list[str]:
    breakdowns = getattr(row, "model_breakdowns", None) or {}
    if not breakdowns:
        return []
    return [
        breakdown.model
        for breakdown in sorted(
            breakdowns.values(),
            key=lambda mb: mb.costs.cost_usd,
            reverse=True,
        )
    ]


def _print_report_footer(console: Console, result: LoadResult, total: Aggregate) -> None:
    events_text = format_int(total.totals.events)
    duplicates_text = format_int(result.duplicates)
    line = f"Events: {events_text} | Duplicates skipped: {duplicates_text}"
    if result.duplicates:
        line += " (same event in multiple log files, counted once)"
    if result.rate_limit_sample_duplicates:
        line += (
            f" | Rate-limit duplicates skipped: {format_int(result.rate_limit_sample_duplicates)}"
        )
    console.print(line)
    if total.costs.vendor_reported_events:
        console.print(
            "Reported vs calculated: "
            f"${total.costs.reported_cost_usd:,.2f} reported | "
            f"${total.costs.calculated_cost_usd:,.2f} calculated | "
            f"${total.costs.reported_calculated_delta_usd:+,.2f} delta"
        )
    if total.cache_savings.cost_usd:
        console.print(
            f"Cache savings: ${total.cache_savings.cost_usd:,.2f} "
            "(vs paying the full input rate for every cached token)"
        )
    if result.tier_sources:
        sources = ", ".join(
            f"{key}={format_int(value)}" for key, value in sorted(result.tier_sources.items())
        )
        console.print(f"Service-tier sources: {sources}")
    if result.plan_types:
        console.print(f"Plan types: {', '.join(sorted(result.plan_types))}")
    _print_accuracy_footer(console, result, total)


def _print_accuracy_footer(console: Console, result: LoadResult, total: Aggregate) -> None:
    dimensions = evidence_dimensions(result, total)
    by_name = {dimension.name: dimension for dimension in dimensions}
    cost_names = ("usage", "model", "tier", "pricing", "project")
    cost_dimensions = [by_name[name] for name in cost_names if name in by_name]
    cost_grade = worst_grade([dimension.grade for dimension in cost_dimensions])
    cost_reasons = [reason for dimension in cost_dimensions for reason in dimension.reasons]
    cost_detail = f" ({cost_reasons[0]})" if cost_reasons else ""
    console.print(f"Cost evidence: {cost_grade}{cost_detail}")
    git = by_name.get("git_attribution")
    if git is not None:
        git_detail = f" ({git.reasons[0]})" if git.reasons else ""
        console.print(f"Git attribution: {git.grade}{git_detail}")


def _table_int(value: int, options: RuntimeOptions) -> str:
    return compact_number(value) if options.compact else format_int(value)


def _table_float(value: Any, options: RuntimeOptions, prefix: str = "") -> str:
    if options.compact:
        return compact_number(value, prefix=prefix)
    if prefix:
        return f"{prefix}{decimal_value(value):,.2f}"
    return f"{decimal_value(value):,.2f}"


def _unsupported_cost(costs: CostTotals) -> bool:
    return (
        costs.unpriced_events > 0
        and costs.vendor_reported_events == 0
        and decimal_value(costs.cost_usd) == 0
        and decimal_value(costs.calculated_cost_usd) == 0
    )


def _cost_cell(costs: CostTotals, options: RuntimeOptions) -> str:
    if _unsupported_cost(costs):
        return "n/a"
    return _table_float(costs.cost_usd, options, prefix="$")


def _calculated_cost(costs: CostTotals, options: RuntimeOptions) -> str:
    if costs.unpriced_events and decimal_value(costs.calculated_cost_usd) == 0:
        return "n/a"
    return _table_float(costs.calculated_cost_usd, options, prefix="$")


def _reported_cost(costs: CostTotals, options: RuntimeOptions) -> str:
    if not costs.vendor_reported_events:
        return "-"
    return _table_float(costs.reported_cost_usd, options, prefix="$")


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
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_1h_tokens",
            "cached_input_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "total_tokens",
            "cost_usd",
            "reported_cost_usd",
            "calculated_cost_usd",
            "reported_minus_calculated_cost_usd",
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


def render_markdown(
    rows: list[Aggregate],
    show_prompts: bool,
    *,
    total: Aggregate | None = None,
) -> str:
    """Render a Markdown table.

    The optional ``total`` row, when supplied by the caller, is rendered
    verbatim instead of being computed by summing ``rows``. This keeps
    overview-style output honest: its rows are overlapping rolling
    windows (7d/30d/90d), so summing them would triple-count spend.
    For grouped commands (daily/weekly/monthly) where rows are
    non-overlapping, the caller can omit ``total`` and the row sum is
    used as before.
    """
    headers = [
        "Group",
        "Events",
        "Input",
        "Cached",
        "Output",
        "Total",
        "Cost $",
        "Reported $",
        "Calc $",
        "Pricing",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    summed_tokens = TokenTotals()
    summed_costs = CostTotals()
    row_statuses: set[str] = set()
    for row in rows:
        row_statuses.add(pricing_status(row))
        summed_tokens.events += row.totals.events
        summed_tokens.input_tokens += row.totals.input_tokens
        summed_tokens.cached_input_tokens += row.totals.cached_input_tokens
        summed_tokens.output_tokens += row.totals.output_tokens
        summed_tokens.total_tokens += row.totals.total_tokens
        summed_costs.add(row.costs)
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
                    f"{row.costs.cost_usd:.2f}",
                    (
                        f"{row.costs.reported_cost_usd:.2f}"
                        if row.costs.vendor_reported_events
                        else ""
                    ),
                    f"{row.costs.calculated_cost_usd:.2f}",
                    pricing_status(row),
                ]
            )
            + " |"
        )
    if rows:
        if total is not None:
            total_tokens = total.totals
            total_costs = total.costs
            total_status = pricing_status(total)
        else:
            total_tokens = summed_tokens
            total_costs = summed_costs
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
                    str(total_tokens.events),
                    str(total_tokens.input_tokens),
                    str(total_tokens.cached_input_tokens),
                    str(total_tokens.output_tokens),
                    str(total_tokens.total_tokens),
                    f"{total_costs.cost_usd:.2f}",
                    f"{total_costs.reported_cost_usd:.2f}"
                    if total_costs.vendor_reported_events
                    else "",
                    f"{total_costs.calculated_cost_usd:.2f}",
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
    total: Aggregate | None = None,
) -> None:
    card = _rate_card(options)
    if output_format == "json":
        text = render_json(result, options, rows, command, rate_card=card)
    elif output_format == "csv":
        text = render_csv(rows, options.show_prompts)
    elif output_format == "markdown":
        text = render_markdown(rows, options.show_prompts, total=total)
    else:
        text = render_table(
            result,
            options,
            rows,
            f"Caliper - {command.title()}",
            rate_card=card,
            total=total,
        )
    write_output(text, output)


LIMITS_CSV_FIELDS = (
    "timestamp",
    "session_id",
    "limit_id",
    "limit_name",
    "plan_type",
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
    console.print("[bold]Caliper - Limits[/bold]")
    console.print(f"Window: {window_label(options.start, options.end, options.timezone)}")
    samples = _recent_samples(result.rate_limit_samples, options.top_threads)
    if not samples:
        console.print("No rate-limit samples found.")
        return buffer.getvalue()
    if options.compact:
        _print_compact_limit_samples(console, samples)
        return buffer.getvalue()
    console.print(_limits_table(samples, options))
    return buffer.getvalue()


def _print_compact_limit_samples(console: Console, samples: list) -> None:
    for sample in samples:
        limit = sample.limit_name or sample.limit_id or "-"
        console.print(
            f"- {iso_z(sample.timestamp)} | limit={limit} | "
            f"primary={sample.primary_used_percent}%/"
            f"{sample.primary_window_minutes}m reset={sample.primary_resets_at} | "
            f"secondary={sample.secondary_used_percent}%/"
            f"{sample.secondary_window_minutes}m reset={sample.secondary_resets_at}"
        )


def _limits_table(samples: list, options: RuntimeOptions) -> Table:
    table = Table(show_lines=False, expand=not options.compact)
    table.add_column("Time")
    table.add_column("Limit")
    table.add_column("Plan")
    table.add_column("Primary %", justify="right")
    table.add_column("Reset In", justify="right")
    table.add_column("Secondary %", justify="right")
    table.add_column("Reset In", justify="right")
    for sample in samples:
        table.add_row(
            iso_z(sample.timestamp),
            sample.limit_name or sample.limit_id or "-",
            str(sample.plan_type or "-"),
            _percent(sample.primary_used_percent),
            _reset_epoch(sample.primary_resets_at),
            _percent(sample.secondary_used_percent),
            _reset_epoch(sample.secondary_resets_at),
        )
    return table


def _percent(value: Any) -> str:
    return "-" if value is None else f"{float(value):.1f}%"


def _reset_epoch(value: Any) -> str:
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


def _report_rate_limit_samples(samples: list, options: RuntimeOptions) -> list:
    if options.include_all_rate_limit_samples:
        return _recent_samples(samples, 0)
    if options.rate_limit_sample_limit <= 0:
        return []
    return _recent_samples(samples, options.rate_limit_sample_limit)


def render_limits_csv(result: LoadResult, options: RuntimeOptions) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(LIMITS_CSV_FIELDS))
    writer.writeheader()
    for sample in _recent_samples(result.rate_limit_samples, options.top_threads):
        row = rate_limit_sample_to_dict(sample)
        writer.writerow({key: row.get(key, "") for key in LIMITS_CSV_FIELDS})
    return out.getvalue()


def render_limits_markdown(result: LoadResult, options: RuntimeOptions) -> str:
    headers = ["Timestamp", "Limit", "Plan", "Primary %", "Secondary %"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for sample in _recent_samples(result.rate_limit_samples, options.top_threads):
        primary = sample.primary_used_percent
        secondary = sample.secondary_used_percent
        lines.append(
            "| "
            + " | ".join(
                [
                    iso_z(sample.timestamp),
                    sample.limit_name or sample.limit_id or "",
                    str(sample.plan_type or ""),
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
        json_options = replace(
            options,
            rate_limit_sample_limit=options.top_threads,
            include_all_rate_limit_samples=options.top_threads == 0,
        )
        text = render_json(result, json_options, [], "limits", rate_card=_rate_card(options))
    elif output_format == "csv":
        text = render_limits_csv(result, options)
    elif output_format == "markdown":
        text = render_limits_markdown(result, options)
    else:
        text = render_limits_table(result, options)
    write_output(text, output)
