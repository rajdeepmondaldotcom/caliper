from __future__ import annotations

import calendar
import csv
import datetime as dt
import html
import io
import json
import os
import re
import sqlite3
import subprocess
import urllib.request
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from codex_meter import __version__
from codex_meter.aggregation import (
    aggregate_daily,
    aggregate_model_mode,
    aggregate_monthly,
    aggregate_projects,
    aggregate_sessions,
    aggregate_total,
    aggregate_weekly,
)
from codex_meter.budgets import (
    SEVERITY_BREACH,
    SEVERITY_EXIT_CODE,
    SEVERITY_WARN,
    Budget,
    BudgetAlert,
    max_severity,
    parse_budgets_table,
)
from codex_meter.budgets import (
    evaluate as evaluate_budgets,
)
from codex_meter.config import build_options, load_config
from codex_meter.exporters import (
    ReceiptInputs,
    month_bounds,
    render_grafana_dashboard,
    render_receipt_html,
    render_receipt_markdown,
)
from codex_meter.forecasts import project as project_forecast
from codex_meter.humanize import short_table_label
from codex_meter.insights import build_insights, insights_payload, render_insights_markdown
from codex_meter.intervals import Interval, parse_interval
from codex_meter.live import run_live
from codex_meter.models import Aggregate, LoadResult, RuntimeOptions
from codex_meter.parse_cache import default_cache_path
from codex_meter.parser import load_usage
from codex_meter.pricing import (
    MODEL_CARDS,
    MODELS_BY_NAME,
    PRICING_SOURCES,
    RateCard,
    normalize_model,
)
from codex_meter.render import format_int, render, render_limits
from codex_meter.timeutil import iso_z, local_timezone

app = typer.Typer(
    help="Offline-first Codex usage reports for tokens, credits, costs, sessions, and projects.",
    no_args_is_help=False,
)
console = Console()

OUTPUT_FORMATS = ("table", "json", "csv", "markdown")

SinceOpt = Annotated[
    str | None,
    typer.Option("--since", "-s", help="Start date/time. Supports YYYY-MM-DD, YYYYMMDD, or ISO."),
]
UntilOpt = Annotated[
    str | None, typer.Option("--until", "-u", help="End date/time. Defaults to now.")
]
DaysOpt = Annotated[float | None, typer.Option("--days", help="Rolling day window before --until.")]
TimezoneOpt = Annotated[
    str, typer.Option("--timezone", "-z", help="Timezone for grouping. Use local or an IANA name.")
]
SessionRootOpt = Annotated[
    Path | None, typer.Option("--session-root", help="Codex session JSONL root.")
]
StateDbOpt = Annotated[Path | None, typer.Option("--state-db", help="Codex state_5.sqlite path.")]
CodexConfigOpt = Annotated[
    Path | None, typer.Option("--codex-config", help="Codex config.toml path.")
]
ConfigOpt = Annotated[Path | None, typer.Option("--config", help="codex-meter config TOML path.")]
PricingModeOpt = Annotated[str, typer.Option("--pricing-mode")]
ServiceTierOpt = Annotated[str, typer.Option("--service-tier")]
UnknownTierOpt = Annotated[str, typer.Option("--unknown-service-tier")]
TierOverridesOpt = Annotated[Path | None, typer.Option("--tier-overrides")]
RatesFileOpt = Annotated[Path | None, typer.Option("--rates-file")]
NoDedupeOpt = Annotated[bool, typer.Option("--no-dedupe")]
NoParseCacheOpt = Annotated[bool, typer.Option("--no-parse-cache")]
DefaultModelOpt = Annotated[str, typer.Option("--default-model")]
ShowPromptsOpt = Annotated[bool, typer.Option("--show-prompts")]
OfflineOpt = Annotated[bool, typer.Option("--offline/--no-offline")]
CompactOpt = Annotated[bool, typer.Option("--compact")]
WidthOpt = Annotated[int | None, typer.Option("--width", help="Table width override.")]
TopThreadsOpt = Annotated[int, typer.Option("--top", "--top-threads", help="Limit grouped rows.")]
FormatOpt = Annotated[str, typer.Option("--format", "-f", help="table, json, csv, or markdown.")]
OutputOpt = Annotated[Path | None, typer.Option("--output", help="Write output to a file.")]

RowsFn = Callable[[LoadResult, RuntimeOptions], list[Aggregate]]

OPTION_KEYS = (
    "since",
    "until",
    "days",
    "timezone",
    "session_root",
    "state_db",
    "codex_config",
    "config",
    "pricing_mode",
    "service_tier",
    "unknown_service_tier",
    "tier_overrides",
    "rates_file",
    "no_dedupe",
    "no_parse_cache",
    "default_model",
    "show_prompts",
    "offline",
    "compact",
    "width",
    "top_threads",
)


def _exit_error(message: str) -> typer.Exit:
    console.print(f"[red]error:[/red] {message}")
    return typer.Exit(2)


def _validate_format(output_format: str) -> None:
    if output_format not in OUTPUT_FORMATS:
        raise _exit_error(f"--format must be one of: {', '.join(OUTPUT_FORMATS)}")


def _records_to_csv(records: list[dict]) -> str:
    if not records:
        return ""
    out = io.StringIO()
    fields = list(records[0].keys())
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(records)
    return out.getvalue()


def _records_to_markdown(records: list[dict]) -> str:
    if not records:
        return "_No data._\n"
    fields = list(records[0].keys())
    lines = [
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join(["---"] * len(fields)) + " |",
    ]
    for record in records:
        lines.append(
            "| "
            + " | ".join(str(record.get(field, "")).replace("|", "\\|") for field in fields)
            + " |"
        )
    return "\n".join(lines) + "\n"


def _options(values: dict) -> RuntimeOptions:
    kwargs = {key: values[key] for key in OPTION_KEYS if key in values}
    try:
        return build_options(**kwargs)
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc


def _run_grouped(name: str, rows_fn: RowsFn, values: dict) -> None:
    _validate_format(values["output_format"])
    options = _options(values)
    result = load_usage(options)
    rows = rows_fn(result, options)[: options.top_threads]
    render(result, options, rows, name, values["output_format"], values["output"])


def version_callback(value: bool) -> None:
    if value:
        console.print(_version_label())
        raise typer.Exit()


def _version_label() -> str:
    checked = max(source.checked for source in PRICING_SOURCES)
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        sha = ""
    else:
        sha = completed.stdout.strip()
    suffix = f", commit {sha}" if sha else ""
    return f"{__version__} (rates checked {checked}{suffix})"


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-v", callback=version_callback, help="Show version and exit."),
    ] = False,
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    compact: CompactOpt = False,
    width: WidthOpt = None,
) -> None:
    if ctx.invoked_subcommand is None:
        _run_overview(locals())


def _run_overview(values: dict) -> None:
    output_format = values["output_format"]
    _validate_format(output_format)
    now = dt.datetime.now(tz=local_timezone())
    option_values = {key: values[key] for key in OPTION_KEYS if key in values}
    option_values["days"] = 90.0
    option_values["until"] = iso_z(now)
    try:
        longest_options = build_options(**option_values)
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    longest_result = load_usage(longest_options)
    rate_card = RateCard.load(longest_options.rates_file, longest_options.pricing_mode)
    rows: list[Aggregate] = []
    for days in (7, 30, 90):
        start = now - dt.timedelta(days=days)
        events = [event for event in longest_result.events if start <= event.timestamp < now]
        window = LoadResult(
            events=events,
            duplicates=0,
            tier_sources=longest_result.tier_sources,
            plan_types=longest_result.plan_types,
            credit_samples=[],
            warnings=longest_result.warnings,
        )
        rows.append(
            aggregate_total(window, longest_options, label=f"Last {days} days", rate_card=rate_card)
        )
    render(longest_result, longest_options, rows, "overview", output_format, values["output"])


@app.command()
def overview(
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    compact: CompactOpt = False,
    width: WidthOpt = None,
) -> None:
    """Show rolling 7/30/90 day usage."""
    _run_overview(locals())


@app.command()
def daily(
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = None,
    timezone: TimezoneOpt = "local",
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    top_threads: TopThreadsOpt = 10,
) -> None:
    """Show usage grouped by day."""
    _run_grouped("daily", aggregate_daily, locals())


@app.command()
def weekly(
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = None,
    timezone: TimezoneOpt = "local",
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    top_threads: TopThreadsOpt = 10,
) -> None:
    """Show usage grouped by ISO week."""
    _run_grouped("weekly", aggregate_weekly, locals())


@app.command()
def monthly(
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = None,
    timezone: TimezoneOpt = "local",
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    top_threads: TopThreadsOpt = 10,
) -> None:
    """Show usage grouped by month."""
    _run_grouped("monthly", aggregate_monthly, locals())


@app.command(name="session")
def session_command(
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = None,
    timezone: TimezoneOpt = "local",
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    top_threads: TopThreadsOpt = 10,
) -> None:
    """Show usage grouped by Codex session."""
    _run_grouped("session", aggregate_sessions, locals())


@app.command()
def project(
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = None,
    timezone: TimezoneOpt = "local",
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    top_threads: TopThreadsOpt = 10,
) -> None:
    """Show usage grouped by project/cwd."""
    _run_grouped("project", aggregate_projects, locals())


@app.command()
def models(
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = None,
    timezone: TimezoneOpt = "local",
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    top_threads: TopThreadsOpt = 10,
) -> None:
    """Show usage grouped by model and service tier."""
    _run_grouped("models", aggregate_model_mode, locals())


@app.command()
def limits(
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = 7,
    timezone: TimezoneOpt = "local",
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    top_threads: TopThreadsOpt = 10,
) -> None:
    """Show recent rate-limit and credit samples."""
    _validate_format(output_format)
    options = _options(locals())
    result = load_usage(options)
    render_limits(result, options, output_format, output)


@app.command()
def insights(
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = None,
    timezone: TimezoneOpt = "local",
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    top_threads: TopThreadsOpt = 10,
) -> None:
    """Surface actionable usage patterns and cost-saving opportunities."""
    if output_format not in {"table", "json", "markdown"}:
        raise _exit_error("--format must be one of: table, json, markdown")
    options = _options(locals())
    result = load_usage(options)
    card = RateCard.load(options.rates_file, options.pricing_mode)
    items = build_insights(result, options, rate_card=card)[: options.top_threads]
    if output_format == "json":
        text = json.dumps(insights_payload(items), indent=2) + "\n"
    elif output_format == "markdown":
        text = render_insights_markdown(items)
    else:
        text = _render_insights_table(items)
    if output:
        output.expanduser().write_text(text)
    else:
        typer.echo(text, nl=False)


def _render_insights_table(items) -> str:
    buffer = io.StringIO()
    local_console = Console(file=buffer, width=120, _environ={})
    local_console.print("[bold]Codex Meter - Insights[/bold]")
    if not items:
        local_console.print("No insights for this window.")
        return buffer.getvalue()
    table = Table(show_lines=False, expand=True)
    table.add_column("Severity")
    table.add_column("Insight")
    table.add_column("Detail")
    table.add_column("Action")
    for item in items:
        table.add_row(item.severity, item.title, item.detail, item.action)
    local_console.print(table)
    return buffer.getvalue()


@app.command()
def tail(
    n: Annotated[int, typer.Option("--n", min=1, help="Number of recent records.")] = 20,
    by: Annotated[str, typer.Option("--by", help="event or session.")] = "event",
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = None,
    timezone: TimezoneOpt = "local",
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    top_threads: TopThreadsOpt = 10,
) -> None:
    """Show the most recent usage events or sessions."""
    del top_threads
    if by not in {"event", "session"}:
        raise _exit_error("--by must be one of: event, session")
    if output_format not in {"table", "json", "csv"}:
        raise _exit_error("--format must be one of: table, json, csv")
    options = _options(locals() | {"top_threads": n})
    result = load_usage(options)
    rows = _recent_tail_rows(result, n, by)
    if output_format == "json":
        text = json.dumps({"by": by, f"{by}s": rows}, indent=2) + "\n"
    elif output_format == "csv":
        text = _tail_csv(rows)
    else:
        text = _tail_table(rows, by, options)
    if output:
        output.expanduser().write_text(text)
    else:
        typer.echo(text, nl=False)


def _recent_tail_rows(result: LoadResult, n: int, by: str) -> list[dict]:
    events = sorted(result.events, key=lambda event: event.timestamp, reverse=True)
    if by == "event":
        return [_tail_event_dict(event) for event in events[:n]]
    seen: set[str] = set()
    rows: list[dict] = []
    for event in events:
        if event.session_id in seen:
            continue
        seen.add(event.session_id)
        item = _tail_event_dict(event)
        item["label"] = event.thread.title or event.thread.first_user_message or event.session_id
        rows.append(item)
        if len(rows) >= n:
            break
    return rows


def _tail_event_dict(event) -> dict:
    return {
        "timestamp": iso_z(event.timestamp),
        "session_id": event.session_id,
        "model": event.model,
        "service_tier": event.service_tier,
        "input_tokens": event.usage.input_tokens,
        "cached_input_tokens": event.usage.cached_input_tokens,
        "output_tokens": event.usage.output_tokens,
        "reasoning_output_tokens": event.usage.reasoning_output_tokens,
        "total_tokens": event.usage.total_tokens,
        "project": event.thread.cwd,
    }


def _tail_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def _tail_table(rows: list[dict], by: str, options: RuntimeOptions) -> str:
    buffer = io.StringIO()
    local_console = Console(file=buffer, width=options.width or 120, _environ={})
    local_console.print(f"[bold]Codex Meter - Recent {by.title()}s[/bold]")
    table = Table(show_lines=False, expand=True)
    table.add_column("Time")
    table.add_column("Model")
    table.add_column("Tier")
    table.add_column("Tokens", justify="right")
    table.add_column("Project")
    for row in rows:
        table.add_row(
            row["timestamp"],
            row["model"],
            row["service_tier"],
            format_int(row["total_tokens"]),
            row.get("project") or "-",
        )
    local_console.print(table)
    return buffer.getvalue()


_DOCTOR_STATUS_STYLES = {"ok": "green", "warn": "yellow", "fail": "red"}
_DOCTOR_EXIT_CODES = {"ok": 0, "warn": 1, "fail": 2}


def _doctor_check(label: str, status: str, detail: str) -> tuple[str, str, str]:
    return label, status, detail


def _check_codex_cli_version() -> tuple[str, str, str]:
    import subprocess

    try:
        completed = subprocess.run(  # noqa: S603 — codex on PATH, no shell.
            ["codex", "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except FileNotFoundError:
        return _doctor_check("Codex CLI", "warn", "not found on PATH; install Codex for live data.")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return _doctor_check("Codex CLI", "warn", f"could not invoke (`{exc}`)")
    version = (completed.stdout or completed.stderr or "").strip().splitlines()[0:1]
    return _doctor_check("Codex CLI", "ok", version[0] if version else "found")


def _check_clock_skew(events) -> tuple[str, str, str]:
    if not events:
        return _doctor_check("Clock", "ok", "no events to compare")
    latest = max(event.timestamp for event in events)
    now = dt.datetime.now(tz=dt.UTC)
    skew = (latest - now).total_seconds()
    detail = _clock_skew_detail(skew)
    if abs(skew) <= 300:
        return _doctor_check("Clock", "ok", f"latest event {detail}")
    if abs(skew) <= 86400:
        return _doctor_check("Clock", "warn", f"latest event {detail}")
    return _doctor_check("Clock", "fail", f"latest event {detail}")


def _clock_skew_detail(skew_seconds: float) -> str:
    seconds = int(abs(skew_seconds))
    if seconds < 60:
        amount = f"{seconds}s"
    else:
        minutes, rem_seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        amount = f"{hours}h {minutes}m" if hours else f"{minutes}m {rem_seconds}s"
    if skew_seconds > 0:
        return f"{amount} in the future"
    return f"{amount} ago"


def _check_rate_card_age() -> tuple[str, str, str]:
    age = _rate_card_age_days()
    if age <= 30:
        return _doctor_check("Rate card", "ok", f"checked {age} days ago")
    if age <= 90:
        return _doctor_check("Rate card", "warn", f"checked {age} days ago")
    return _doctor_check(
        "Rate card",
        "fail",
        f"checked {age} days ago — run `codex-meter rates show` and consider updating.",
    )


def _check_state_db_readable(path: Path) -> tuple[str, str, str]:
    if not path.exists():
        return _doctor_check("State DB readable", "warn", "state DB is missing")
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            conn.execute("select count(*) from sqlite_master").fetchone()
    except sqlite3.Error as exc:
        return _doctor_check("State DB readable", "warn", f"could not open read-only: {exc}")
    return _doctor_check("State DB readable", "ok", "read-only open succeeded")


def _check_rates_file(path: Path | None) -> tuple[str, str, str]:
    if path is None:
        return _doctor_check("Rates file", "ok", "using embedded rate card")
    try:
        RateCard.load(path)
    except ValueError as exc:
        return _doctor_check("Rates file", "fail", str(exc))
    return _doctor_check("Rates file", "ok", str(path))


def _check_python_version() -> tuple[str, str, str]:
    import sys

    info = sys.version_info
    if info < (3, 11):
        return _doctor_check("Python", "fail", f"{info.major}.{info.minor} — requires >= 3.11")
    return _doctor_check("Python", "ok", f"{info.major}.{info.minor}.{info.micro}")


@app.command()
def doctor(
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="table, json, csv, or markdown."),
    ] = "table",
) -> None:
    """Check local Codex data paths, rate-card age, clock skew, and tooling."""
    _validate_format(output_format)
    try:
        options = build_options(
            days=7.0,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    files = list(options.session_root.glob("**/*.jsonl")) if options.session_root.exists() else []
    result = load_usage(options) if files else None
    checks: list[tuple[str, str, str]] = []
    checks.append(_check_python_version())
    checks.append(
        _doctor_check(
            "Session root",
            "ok" if options.session_root.exists() else "fail",
            f"{options.session_root} ({format_int(len(files))} JSONL files)",
        )
    )
    checks.append(
        _doctor_check(
            "State DB",
            "ok" if options.state_db.exists() else "warn",
            str(options.state_db),
        )
    )
    checks.append(_check_state_db_readable(options.state_db))
    checks.append(
        _doctor_check(
            "Codex config",
            "ok" if options.config_path.exists() else "warn",
            str(options.config_path),
        )
    )
    checks.append(_check_codex_cli_version())
    checks.append(_check_rate_card_age())
    checks.append(_check_rates_file(options.rates_file))
    checks.append(_doctor_check("Parse cache", "ok", str(default_cache_path())))
    checks.append(_check_clock_skew(result.events if result else []))
    if result:
        checks.append(
            _doctor_check("Events loaded", "ok", f"{len(result.events):,} in last 7 days")
        )
        if result.events:
            inferred = result.tier_sources.get("assumed", 0) + result.tier_sources.get(
                "current-config", 0
            )
            if inferred == len(result.events):
                checks.append(
                    _doctor_check(
                        "Tier coverage",
                        "warn",
                        "No events recorded a tier; pin one with --service-tier "
                        "or --tier-overrides.",
                    )
                )
        if result.warnings:
            for warning in result.warnings:
                checks.append(_doctor_check("Parser warning", "warn", warning))

    worst = "ok"
    severity_rank = {"ok": 0, "warn": 1, "fail": 2}
    for _, status, _detail in checks:
        if severity_rank[status] > severity_rank[worst]:
            worst = status

    if output_format == "json":
        typer.echo(
            json.dumps(
                {
                    "checks": [
                        {"label": label, "status": status, "detail": detail}
                        for label, status, detail in checks
                    ],
                    "worst": worst,
                },
                indent=2,
            )
        )
        raise typer.Exit(_DOCTOR_EXIT_CODES[worst])

    if output_format == "csv":
        check_records = [
            {"label": label, "status": status, "detail": detail} for label, status, detail in checks
        ]
        typer.echo(
            _records_to_csv(check_records),
            nl=False,
        )
        raise typer.Exit(_DOCTOR_EXIT_CODES[worst])

    if output_format == "markdown":
        check_records = [
            {"label": label, "status": status, "detail": detail} for label, status, detail in checks
        ]
        typer.echo(
            _records_to_markdown(check_records),
            nl=False,
        )
        raise typer.Exit(_DOCTOR_EXIT_CODES[worst])

    console.print("[bold]Codex Meter - Doctor[/bold]")
    table = Table(show_lines=False)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for label, status, detail in checks:
        style = _DOCTOR_STATUS_STYLES[status]
        table.add_row(label, f"[{style}]{status.upper()}[/{style}]", detail)
    console.print(table)
    console.print(
        f"Overall: [{_DOCTOR_STATUS_STYLES[worst]}]{worst.upper()}[/{_DOCTOR_STATUS_STYLES[worst]}]"
    )
    raise typer.Exit(_DOCTOR_EXIT_CODES[worst])


@app.command()
def init(
    path: Annotated[
        Path,
        typer.Option("--path", help="Target file path."),
    ] = Path(".codex-meter.toml"),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing config."),
    ] = False,
) -> None:
    """Scaffold a .codex-meter.toml config with commented defaults."""
    if path.exists() and not force:
        raise _exit_error(f"{path} already exists. Pass --force to overwrite.")
    template = (
        "# codex-meter configuration.\n"
        "# Tip: every key here can also be set per-invocation via a CLI flag.\n"
        "\n"
        "# Default rolling window for `codex-meter` (days).\n"
        "default_days = 30\n"
        '# timezone = "local"\n'
        "\n"
        "# Local Codex data paths.\n"
        '# session_root = "~/.codex/sessions"\n'
        '# state_db = "~/.codex/state_5.sqlite"\n'
        '# codex_config = "~/.codex/config.toml"\n'
        "\n"
        "# Pricing behavior. model = per-model card; flat = default fallback rates.\n"
        '# pricing_mode = "model"\n'
        '# rates_file = "./rates.json"\n'
        "\n"
        "# Service-tier inference. auto = use precedence chain.\n"
        'service_tier = "auto"\n'
        'unknown_service_tier = "current-config"\n'
        '# tier_overrides = "./tier-overrides.json"\n'
        "\n"
        "# Default model when none is recorded.\n"
        'default_model = "gpt-5.5"\n'
        "\n"
        "# Output and privacy defaults.\n"
        "# show_prompts = false\n"
        "# offline = true\n"
        "# compact = false\n"
        "# width = 140\n"
        "# top_threads = 10\n"
        "# no_dedupe = false\n"
        "# no_parse_cache = false\n"
        "\n"
        "# Optional budgets — used by `codex-meter budgets check`.\n"
        "# Severity: ok < 80%, warn at 80%, breach at 100%.\n"
        "[budgets]\n"
        "# daily_credits = 25000\n"
        "# weekly_credits = 100000\n"
        "# monthly_credits = 400000\n"
        "# weekly_api_dollars = 50.0\n"
        "\n"
        "# Or use the nested form to set warn_at per period:\n"
        "# [budgets.monthly]\n"
        "# credits = 500000\n"
        "# warn_at = 0.7\n"
    )
    path.write_text(template)
    console.print(f"[green]Wrote[/green] {path}")
    console.print("[dim]Edit it, then run `codex-meter budgets check` to verify.[/dim]")


rates_app = typer.Typer(help="Inspect and manage the embedded Codex rate card.")
app.add_typer(rates_app, name="rates")


def _rate_card_age_days() -> int:
    today = dt.date.today()
    ages: list[int] = []
    for source in PRICING_SOURCES:
        try:
            checked = dt.date.fromisoformat(source.checked)
        except ValueError:
            continue
        ages.append((today - checked).days)
    return max(ages) if ages else 0


def _format_rates_label(rates: object) -> str:
    if rates is None:
        return "—"
    return (
        f"in={rates.input:g} cached={rates.cached_input:g} "
        f"out={rates.output:g} reason={rates.effective_reasoning_output:g}"
    )


@rates_app.command("show")
def rates_show(
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="table, json, csv, or markdown."),
    ] = "table",
) -> None:
    """Show the active rate card, sources, and age."""
    _validate_format(output_format)

    age = _rate_card_age_days()
    stale = age > 90

    payload = {
        "checked": [
            {"name": source.name, "url": source.url, "checked": source.checked}
            for source in PRICING_SOURCES
        ],
        "age_days": age,
        "stale": stale,
        "models": [
            {
                "name": card.name,
                "api": (
                    {
                        "input": card.api_rates.input,
                        "cached_input": card.api_rates.cached_input,
                        "output": card.api_rates.output,
                        "reasoning_output": card.api_rates.effective_reasoning_output,
                    }
                    if card.api_rates
                    else None
                ),
                "credits": {
                    "input": card.credit_rates.input,
                    "cached_input": card.credit_rates.cached_input,
                    "output": card.credit_rates.output,
                    "reasoning_output": card.credit_rates.effective_reasoning_output,
                },
                "fast_multiplier": card.fast_multiplier,
                "long_context": (
                    {
                        "threshold": card.long_context.threshold,
                        "input_mult": card.long_context.input_mult,
                        "output_mult": card.long_context.output_mult,
                    }
                    if card.long_context
                    else None
                ),
            }
            for card in MODEL_CARDS
        ],
    }
    if output_format == "json":
        typer.echo(json.dumps(payload, indent=2))
        return
    if output_format in {"csv", "markdown"}:
        records = [
            {
                "model": card["name"],
                "fast_multiplier": card["fast_multiplier"],
                "api_input": (card["api"] or {}).get("input", ""),
                "credits_input": card["credits"]["input"],
            }
            for card in payload["models"]
        ]
        text = _records_to_csv(records) if output_format == "csv" else _records_to_markdown(records)
        typer.echo(text, nl=False)
        return

    console.print("[bold]Codex Meter - Rate Card[/bold]")
    console.print(f"Age: {age} days{'  [red](stale; consider refreshing)[/red]' if stale else ''}")
    for source in PRICING_SOURCES:
        console.print(f"- {source.name} (checked {source.checked}) — {source.url}")
    console.print()

    table = Table(title="Models")
    table.add_column("Model")
    table.add_column("Fast×", justify="right")
    table.add_column("Long context")
    table.add_column("API ($/M)")
    table.add_column("Credits (/M)")
    for card in MODEL_CARDS:
        long_ctx = (
            f">{format_int(card.long_context.threshold)} → "
            f"in×{card.long_context.input_mult:g}, out×{card.long_context.output_mult:g}"
            if card.long_context
            else "—"
        )
        table.add_row(
            card.name,
            f"{card.fast_multiplier:g}",
            long_ctx,
            _format_rates_label(card.api_rates),
            _format_rates_label(card.credit_rates),
        )
    console.print(table)


@rates_app.command("refresh")
def rates_refresh(
    allow_network: Annotated[
        bool,
        typer.Option("--allow-network", help="Fetch pricing pages over the network."),
    ] = False,
    output: OutputOpt = None,
) -> None:
    """Refresh a local fetched rate-card snapshot. Offline unless --allow-network is set."""
    if not allow_network:
        raise _exit_error(
            "rates refresh needs --allow-network. The default path stays offline; pass "
            "--allow-network to fetch an audit snapshot, or use --rates-file to override locally."
        )
    target = output or _fetched_rates_path()
    payload = _fetch_rate_sources()
    target.expanduser().parent.mkdir(parents=True, exist_ok=True)
    target.expanduser().write_text(json.dumps(payload, indent=2) + "\n")
    console.print(f"[green]Wrote[/green] {target}")


def _fetched_rates_path() -> Path:
    override = os.environ.get("CODEX_METER_DATA_DIR")
    if override:
        return Path(override).expanduser() / "rates-fetched.json"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "codex-meter" / "rates-fetched.json"
    return Path.home() / ".local" / "share" / "codex-meter" / "rates-fetched.json"


def _fetch_rate_sources() -> dict:
    sources = []
    observed = []
    for source in PRICING_SOURCES:
        request = urllib.request.Request(
            source.url,
            headers={"User-Agent": f"codex-meter/{__version__}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read()
        except OSError as exc:
            sources.append(
                {"name": source.name, "url": source.url, "status": "error", "error": str(exc)}
            )
            continue
        text = body.decode("utf-8", errors="replace")
        extracted = _extract_models_from_text(text)
        sources.append(
            {
                "name": source.name,
                "url": source.url,
                "status": "ok",
                "bytes": len(body),
                "observed_models": len(extracted),
            }
        )
        observed.extend(item | {"source": source.name} for item in extracted)
    observed_models = _dedupe_models(observed)
    return {
        "fetched_at": iso_z(dt.datetime.now(tz=dt.UTC)),
        "sources": sources,
        "embedded_models": _embedded_rate_snapshot(),
        "observed_models": observed_models,
        "models": observed_models,
        "discrepancies": _rate_discrepancies(observed_models),
    }


def _extract_models_from_text(text: str) -> list[dict]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return _extract_models_from_html(text)
    if isinstance(raw, dict) and isinstance(raw.get("models"), list):
        return [item for item in raw["models"] if isinstance(item, dict) and item.get("name")]
    return []


def _extract_models_from_html(text: str) -> list[dict]:
    normalized = _normal_text(text)
    found: list[dict] = []
    for card in MODEL_CARDS:
        window = _window_for_model(normalized, card.name)
        if not window:
            continue
        api_rates = _extract_api_rates(window)
        credit_rates = _extract_credit_rates(window, card.name)
        item: dict = {"name": card.name}
        if api_rates:
            item["api"] = api_rates
        if credit_rates:
            item["credits"] = credit_rates
        if len(item) > 1:
            found.append(item)
    return found


def _normal_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u2011", "-").replace("\u2010", "-").replace("\u2013", "-")
    text = text.replace("\u2014", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _window_for_model(text: str, model: str) -> str:
    candidates = [
        text[match.start() : match.start() + 3500]
        for match in re.finditer(re.escape(model), text, flags=re.IGNORECASE)
    ]
    for candidate in candidates:
        lowered = candidate.lower()
        if "per 1m tokens" in lowered or "credits" in lowered:
            return candidate
    return candidates[0] if candidates else ""


def _extract_api_rates(window: str) -> dict | None:
    match = re.search(
        r"Per 1M tokens\s+Input\s+\$([0-9.]+)\s+Cached input\s+\$([0-9.]+)\s+Output\s+\$([0-9.]+)",
        window,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "input": float(match.group(1)),
        "cached_input": float(match.group(2)),
        "output": float(match.group(3)),
    }


def _extract_credit_rates(window: str, model: str) -> dict | None:
    display = re.escape(model.replace("gpt", "GPT"))
    match = re.search(
        rf"{display}\s+([0-9.]+)\s+credits\s+([0-9.]+)\s+credits\s+([0-9.]+)\s+credits",
        window,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "input": float(match.group(1)),
        "cached_input": float(match.group(2)),
        "output": float(match.group(3)),
    }


def _dedupe_models(models: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for model in models:
        name = str(model["name"])
        merged = deduped.setdefault(name, {"name": name})
        for key, value in model.items():
            if key == "name":
                continue
            if key == "source" and merged.get("source") and merged["source"] != value:
                merged["source"] = f"{merged['source']}; {value}"
                continue
            merged[key] = value
    return [deduped[key] for key in sorted(deduped)]


def _rates_payload(rates) -> dict | None:
    if rates is None:
        return None
    return {
        "input": rates.input,
        "cached_input": rates.cached_input,
        "output": rates.output,
        "reasoning_output": rates.effective_reasoning_output,
    }


def _embedded_rate_snapshot() -> list[dict]:
    return [
        {
            "name": card.name,
            "api": _rates_payload(card.api_rates),
            "credits": _rates_payload(card.credit_rates),
            "fast_multiplier": card.fast_multiplier,
        }
        for card in MODEL_CARDS
    ]


def _rate_discrepancies(observed_models: list[dict]) -> list[dict]:
    discrepancies: list[dict] = []
    for observed in observed_models:
        card = MODELS_BY_NAME.get(normalize_model(str(observed.get("name") or "")))
        if card is None:
            continue
        for section, rates in (("api", card.api_rates), ("credits", card.credit_rates)):
            if not rates or not isinstance(observed.get(section), dict):
                continue
            expected = _rates_payload(rates) or {}
            for field in ("input", "cached_input", "output"):
                actual = observed[section].get(field)
                if actual is None:
                    continue
                if abs(float(actual) - float(expected[field])) > 1e-9:
                    discrepancies.append(
                        {
                            "model": card.name,
                            "section": section,
                            "field": field,
                            "embedded": expected[field],
                            "observed": actual,
                        }
                    )
    return discrepancies


def _daily_credit_series(events, options: RuntimeOptions, rate_card: RateCard) -> list[float]:
    """Sum adjusted credits per local-tz day across the given events."""
    result = LoadResult(
        events=list(events),
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
    )
    rows = aggregate_daily(result, options, rate_card=rate_card)
    return [row.costs.adjusted_credits for row in rows]


def _days_remaining_in_month(now: dt.datetime) -> int:
    import calendar

    last_day = calendar.monthrange(now.year, now.month)[1]
    return max(0, last_day - now.day)


@app.command()
def forecast(
    days: Annotated[
        int,
        typer.Option("--days", min=1, max=180, help="Trailing day window analyzed."),
    ] = 14,
    cap: Annotated[
        float | None,
        typer.Option("--cap", help="Plan credit cap. Compute days-to-depletion."),
    ] = None,
    output_format: FormatOpt = "table",
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    tier_overrides: TierOverridesOpt = None,
    service_tier: ServiceTierOpt = "auto",
    pricing_mode: PricingModeOpt = "model",
) -> None:
    """Project month-end credits + ±1σ band. Optional --cap shows days-to-depletion."""
    if output_format not in {"table", "json"}:
        raise _exit_error("--format must be one of: table, json")
    try:
        options = build_options(
            days=float(days),
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
            tier_overrides=tier_overrides,
            service_tier=service_tier,
            pricing_mode=pricing_mode,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    result = load_usage(options)
    rate_card = RateCard.load(options.rates_file, options.pricing_mode)
    daily = _daily_credit_series(result.events, options, rate_card)
    now = dt.datetime.now(tz=local_timezone())
    days_remaining = _days_remaining_in_month(now)
    projection = project_forecast(daily, days_remaining, unit="credits", cap=cap)

    if output_format == "json":
        import json as _json

        typer.echo(
            _json.dumps(
                {
                    "unit": projection.unit,
                    "days_analyzed": projection.days_analyzed,
                    "daily_mean": projection.daily_mean,
                    "daily_stdev": projection.daily_stdev,
                    "days_remaining": projection.days_remaining,
                    "linear_total": projection.linear_total,
                    "ewma_total": projection.ewma_total,
                    "linear_low": projection.linear_low,
                    "linear_high": projection.linear_high,
                    "cap": projection.cap,
                    "days_to_cap": projection.days_to_cap,
                },
                indent=2,
            )
        )
        return

    from rich.table import Table

    console.print("[bold]Codex Meter - Forecast[/bold]")
    console.print(
        f"Window analyzed: trailing {days} days  ({projection.days_analyzed} days with usage)"
    )
    console.print(f"Days remaining this month: {projection.days_remaining}")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim", justify="right")
    table.add_column()
    table.add_row("Daily mean", f"{projection.daily_mean:,.2f} {projection.unit}")
    table.add_row("Daily σ", f"{projection.daily_stdev:,.2f} {projection.unit}")
    table.add_row("Linear projection", f"{projection.linear_total:,.2f} {projection.unit}")
    table.add_row(
        "  ±1σ band",
        f"{projection.linear_low:,.2f} – {projection.linear_high:,.2f}",
    )
    table.add_row("EWMA projection", f"{projection.ewma_total:,.2f} {projection.unit}")
    if projection.cap is not None and projection.days_to_cap is not None:
        table.add_row("Plan cap", f"{projection.cap:,.2f} {projection.unit}")
        table.add_row("Days to depletion at mean rate", f"{projection.days_to_cap:,.1f}")
    console.print(table)


def _events_in_interval(events, interval: Interval):
    return [event for event in events if interval.start <= event.timestamp < interval.end]


def _aggregate_interval(
    events,
    options: RuntimeOptions,
    rate_card: RateCard,
    interval: Interval,
    label: str,
) -> Aggregate:
    from codex_meter.aggregation import aggregate_total

    filtered = _events_in_interval(events, interval)
    result = LoadResult(
        events=filtered,
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
    )
    return aggregate_total(result, options, label=label, rate_card=rate_card)


@app.command()
def compare(
    a: Annotated[
        str,
        typer.Option("--a", help='Window A expression, e.g. "last 7 days".'),
    ] = "last 7 days",
    b: Annotated[
        str,
        typer.Option("--b", help='Window B expression, e.g. "previous 7 days".'),
    ] = "previous 7 days",
    output_format: FormatOpt = "table",
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    tier_overrides: TierOverridesOpt = None,
    service_tier: ServiceTierOpt = "auto",
    pricing_mode: PricingModeOpt = "model",
) -> None:
    """Compare two windows side-by-side with credit + dollar deltas."""
    if output_format not in {"table", "json"}:
        raise _exit_error("--format must be one of: table, json")

    now = dt.datetime.now(tz=local_timezone())
    try:
        interval_a = parse_interval(a, now)
        interval_b = parse_interval(b, now)
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    earliest = min(interval_a.start, interval_b.start)
    span_days = max(1.0, (now - earliest).total_seconds() / 86400.0) + 1

    try:
        options = build_options(
            days=span_days,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
            tier_overrides=tier_overrides,
            service_tier=service_tier,
            pricing_mode=pricing_mode,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    result = load_usage(options)
    rate_card = RateCard.load(options.rates_file, options.pricing_mode)
    agg_a = _aggregate_interval(result.events, options, rate_card, interval_a, "A")
    agg_b = _aggregate_interval(result.events, options, rate_card, interval_b, "B")

    def _delta(left: float, right: float) -> tuple[float, float]:
        diff = left - right
        pct = (diff / right * 100.0) if right else 0.0
        return diff, pct

    credits_delta, credits_pct = _delta(agg_a.costs.adjusted_credits, agg_b.costs.adjusted_credits)
    dollars_delta, dollars_pct = _delta(agg_a.costs.api_dollars, agg_b.costs.api_dollars)
    tokens_delta, tokens_pct = _delta(agg_a.totals.total_tokens, agg_b.totals.total_tokens)

    if output_format == "json":
        import json as _json

        typer.echo(
            _json.dumps(
                {
                    "a": _interval_summary(interval_a, agg_a),
                    "b": _interval_summary(interval_b, agg_b),
                    "delta": {
                        "credits": credits_delta,
                        "credits_pct": credits_pct,
                        "api_dollars": dollars_delta,
                        "api_dollars_pct": dollars_pct,
                        "tokens": tokens_delta,
                        "tokens_pct": tokens_pct,
                    },
                },
                indent=2,
            )
        )
        return

    from rich.table import Table

    console.print("[bold]Codex Meter - Compare[/bold]")
    console.print(f"A: {interval_a.label}  ({iso_z(interval_a.start)} → {iso_z(interval_a.end)})")
    console.print(f"B: {interval_b.label}  ({iso_z(interval_b.start)} → {iso_z(interval_b.end)})")
    table = Table()
    table.add_column("Metric")
    table.add_column("A", justify="right")
    table.add_column("B", justify="right")
    table.add_column("Δ", justify="right")
    table.add_column("%", justify="right")
    table.add_row(
        "Credits",
        f"{agg_a.costs.adjusted_credits:,.2f}",
        f"{agg_b.costs.adjusted_credits:,.2f}",
        f"{credits_delta:+,.2f}",
        f"{credits_pct:+.1f}%",
    )
    table.add_row(
        "API $",
        f"${agg_a.costs.api_dollars:,.2f}",
        f"${agg_b.costs.api_dollars:,.2f}",
        f"{dollars_delta:+,.2f}",
        f"{dollars_pct:+.1f}%",
    )
    table.add_row(
        "Tokens",
        format_int(agg_a.totals.total_tokens),
        format_int(agg_b.totals.total_tokens),
        f"{tokens_delta:+,.0f}",
        f"{tokens_pct:+.1f}%",
    )
    table.add_row(
        "Events",
        format_int(agg_a.totals.events),
        format_int(agg_b.totals.events),
        "",
        "",
    )
    console.print(table)


def _interval_summary(interval: Interval, agg: Aggregate) -> dict:
    return {
        "label": interval.label,
        "start": iso_z(interval.start),
        "end": iso_z(interval.end),
        "credits": agg.costs.adjusted_credits,
        "standard_credits": agg.costs.standard_credits,
        "api_dollars": agg.costs.api_dollars,
        "events": agg.totals.events,
        "tokens": agg.totals.total_tokens,
        "models": sorted(agg.models),
    }


@app.command()
def whatif(
    days: Annotated[
        int,
        typer.Option("--days", min=1, max=365, help="Trailing day window."),
    ] = 7,
    tier: Annotated[
        str | None,
        typer.Option("--tier", help="Hypothetical tier: standard or fast."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Hypothetical model name (must be in rate card)."),
    ] = None,
    output_format: FormatOpt = "table",
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    tier_overrides: TierOverridesOpt = None,
    service_tier: ServiceTierOpt = "auto",
    pricing_mode: PricingModeOpt = "model",
) -> None:
    """Re-cost the window under a hypothetical tier or model swap."""
    if tier is None and model is None:
        raise _exit_error("Provide --tier and/or --model to evaluate a hypothetical.")
    if tier is not None and tier not in {"standard", "fast"}:
        raise _exit_error("--tier must be one of: standard, fast")
    if model is not None and model not in MODELS_BY_NAME:
        raise _exit_error(
            f"--model {model!r} is not in the embedded rate card. "
            f"Use one of: {', '.join(sorted(MODELS_BY_NAME))}"
        )
    if output_format not in {"table", "json"}:
        raise _exit_error("--format must be one of: table, json")

    try:
        options = build_options(
            days=float(days),
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
            tier_overrides=tier_overrides,
            service_tier=service_tier,
            pricing_mode=pricing_mode,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    result = load_usage(options)
    rate_card = RateCard.load(options.rates_file, options.pricing_mode)
    actual_credits = 0.0
    actual_dollars = 0.0
    hypothetical_credits = 0.0
    hypothetical_dollars = 0.0
    for event in result.events:
        actual, _, _ = rate_card.cost_for(event.usage, event.model, event.service_tier)
        actual_credits += actual.adjusted_credits
        actual_dollars += actual.api_dollars
        hyp_model = model or event.model
        hyp_tier = tier or event.service_tier
        hypothetical, _, _ = rate_card.cost_for(event.usage, hyp_model, hyp_tier)
        hypothetical_credits += hypothetical.adjusted_credits
        hypothetical_dollars += hypothetical.api_dollars

    credit_delta = hypothetical_credits - actual_credits
    dollar_delta = hypothetical_dollars - actual_dollars
    credit_pct = (credit_delta / actual_credits * 100.0) if actual_credits else 0.0
    dollar_pct = (dollar_delta / actual_dollars * 100.0) if actual_dollars else 0.0

    if output_format == "json":
        import json as _json

        typer.echo(
            _json.dumps(
                {
                    "days": days,
                    "hypothetical": {"tier": tier, "model": model},
                    "actual": {
                        "credits": actual_credits,
                        "api_dollars": actual_dollars,
                    },
                    "projected": {
                        "credits": hypothetical_credits,
                        "api_dollars": hypothetical_dollars,
                    },
                    "delta": {
                        "credits": credit_delta,
                        "credits_pct": credit_pct,
                        "api_dollars": dollar_delta,
                        "api_dollars_pct": dollar_pct,
                    },
                    "events_evaluated": len(result.events),
                },
                indent=2,
            )
        )
        return

    from rich.table import Table

    label_parts = []
    if tier:
        label_parts.append(f"tier={tier}")
    if model:
        label_parts.append(f"model={model}")
    label = ", ".join(label_parts) or "no-op"
    console.print(f"[bold]Codex Meter - What If ({label})[/bold]")
    console.print(f"Trailing {days} days · {len(result.events):,} events")
    table = Table()
    table.add_column("Metric")
    table.add_column("Actual", justify="right")
    table.add_column("Projected", justify="right")
    table.add_column("Δ", justify="right")
    table.add_column("%", justify="right")
    table.add_row(
        "Credits",
        f"{actual_credits:,.2f}",
        f"{hypothetical_credits:,.2f}",
        f"{credit_delta:+,.2f}",
        f"{credit_pct:+.1f}%",
    )
    table.add_row(
        "API $",
        f"${actual_dollars:,.2f}",
        f"${hypothetical_dollars:,.2f}",
        f"{dollar_delta:+,.2f}",
        f"{dollar_pct:+.1f}%",
    )
    console.print(table)


export_app = typer.Typer(help="Generate external artifacts: receipts, Grafana dashboards, etc.")
app.add_typer(export_app, name="export")


def _build_prometheus_snapshot(options: RuntimeOptions):
    """Construct a Prometheus MetricsSnapshot from a freshly loaded usage window."""
    from codex_meter.prom_export import MetricsSnapshot
    from codex_meter.windows import compute_window_state

    result = load_usage(options)
    rate_card = RateCard.load(options.rates_file, options.pricing_mode)
    now = dt.datetime.now(tz=local_timezone())
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_events = [event for event in result.events if event.timestamp >= today_start]
    today_result = LoadResult(
        events=today_events,
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
    )
    from codex_meter.aggregation import aggregate_total

    totals = aggregate_total(today_result, options, label="today", rate_card=rate_card)
    primary = compute_window_state(result.credit_samples, now, "primary")
    secondary = compute_window_state(result.credit_samples, now, "secondary")

    tokens: dict[tuple[str, str, str], int] = {}
    for event in today_events:
        key_input = (event.model or "unknown", event.service_tier or "unknown", "input")
        tokens[key_input] = tokens.get(key_input, 0) + int(event.usage.input_tokens)
        key_cached = (event.model or "unknown", event.service_tier or "unknown", "cached")
        tokens[key_cached] = tokens.get(key_cached, 0) + int(event.usage.cached_input_tokens)
        key_output = (event.model or "unknown", event.service_tier or "unknown", "output")
        tokens[key_output] = tokens.get(key_output, 0) + int(event.usage.output_tokens)
        key_reasoning = (event.model or "unknown", event.service_tier or "unknown", "reasoning")
        tokens[key_reasoning] = tokens.get(key_reasoning, 0) + int(
            event.usage.reasoning_output_tokens
        )

    burn = primary.burn_rate_per_hour
    return MetricsSnapshot(
        credits_used=totals.costs.adjusted_credits,
        burn_per_hour=burn if burn is not None else 0.0,
        primary_window_percent=primary.used_percent if primary.used_percent is not None else 0.0,
        secondary_window_percent=(
            secondary.used_percent if secondary.used_percent is not None else 0.0
        ),
        events_total=totals.totals.events,
        long_context_events_total=totals.long_context_events,
        tokens_total=tokens,
    )


@export_app.command("prometheus")
def export_prometheus(
    host: Annotated[
        str,
        typer.Option("--host", help="Bind address. Default 127.0.0.1 to keep metrics local."),
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="TCP port.")] = 9090,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    tier_overrides: TierOverridesOpt = None,
    service_tier: ServiceTierOpt = "auto",
    pricing_mode: PricingModeOpt = "model",
) -> None:
    """Serve /metrics for Prometheus. Default bind 127.0.0.1 — pass --host 0.0.0.0 to expose."""
    try:
        from codex_meter.prom_export import serve_forever
    except ImportError as exc:
        raise _exit_error(
            "prometheus-client is not installed. Install with: pip install 'codex-meter[prom]'"
        ) from exc
    try:
        options = build_options(
            days=7.0,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
            tier_overrides=tier_overrides,
            service_tier=service_tier,
            pricing_mode=pricing_mode,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    console.print(f"[green]Prometheus exporter listening on http://{host}:{port}/metrics[/green]")
    try:
        serve_forever(host, port, lambda: _build_prometheus_snapshot(options))
    except OSError as exc:
        raise _exit_error(
            f"could not bind {host}:{port}: {exc}. "
            f"Try a different --port or check that no other exporter is running."
        ) from exc


@export_app.command("grafana")
def export_grafana(
    title: Annotated[str, typer.Option("--title", help="Dashboard title.")] = "Codex Meter",
    output: OutputOpt = None,
) -> None:
    """Emit a Grafana dashboard JSON wired to the Prometheus exporter metric names."""
    text = render_grafana_dashboard(title=title)
    if output:
        output.expanduser().write_text(text)
    else:
        typer.echo(text)


@export_app.command("receipt")
def export_receipt(
    month: Annotated[str, typer.Option("--month", help="Month YYYY-MM.")] = "",
    receipt_format: Annotated[
        str,
        typer.Option("--format", "-f", help="markdown or html."),
    ] = "markdown",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    tier_overrides: TierOverridesOpt = None,
    service_tier: ServiceTierOpt = "auto",
    pricing_mode: PricingModeOpt = "model",
    top: Annotated[
        int,
        typer.Option("--top", min=1, max=50, help="Rows in 'top sessions' / 'top projects'."),
    ] = 5,
) -> None:
    """Generate a monthly receipt (markdown or html)."""
    if receipt_format not in {"markdown", "html"}:
        raise _exit_error("--format must be one of: markdown, html")

    now = dt.datetime.now(tz=local_timezone())
    chosen_month = month or now.strftime("%Y-%m")
    try:
        start, end = month_bounds(chosen_month, local_timezone())
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    span_days = (end - start).total_seconds() / 86400.0 + 1
    try:
        options = build_options(
            days=span_days,
            until=iso_z(end),
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
            tier_overrides=tier_overrides,
            service_tier=service_tier,
            pricing_mode=pricing_mode,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    result = load_usage(options)
    rate_card = RateCard.load(options.rates_file, options.pricing_mode)

    in_month = [event for event in result.events if start <= event.timestamp < end]
    scoped = LoadResult(
        events=in_month,
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
    )

    from codex_meter.aggregation import (
        aggregate_model_mode,
        aggregate_projects,
        aggregate_sessions,
        aggregate_total,
    )

    totals = aggregate_total(scoped, options, label="Month", rate_card=rate_card)
    by_model = aggregate_model_mode(scoped, options, rate_card=rate_card)
    top_sessions = aggregate_sessions(scoped, options, rate_card=rate_card)[:top]
    top_projects = aggregate_projects(scoped, options, rate_card=rate_card)[:top]

    payload = ReceiptInputs(
        month=chosen_month,
        totals=totals,
        by_model=by_model,
        top_sessions=top_sessions,
        top_projects=top_projects,
        generated_at=now,
    )
    text = (
        render_receipt_html(payload)
        if receipt_format == "html"
        else render_receipt_markdown(payload)
    )
    if output:
        output.expanduser().write_text(text)
    else:
        typer.echo(text)


budgets_app = typer.Typer(help="Inspect budget alerts (warn/breach) for the active window.")
app.add_typer(budgets_app, name="budgets")


def _current_period_intervals(now: dt.datetime) -> dict[str, tuple[dt.datetime, dt.datetime]]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - dt.timedelta(days=day_start.weekday())
    month_start = day_start.replace(day=1)
    return {
        "daily": (day_start, now),
        "weekly": (week_start, now),
        "monthly": (month_start, now),
    }


def _usage_for_periods(
    events, options: RuntimeOptions, rate_card: RateCard, now: dt.datetime
) -> dict[str, float]:
    from codex_meter.aggregation import aggregate_total

    intervals = _current_period_intervals(now)
    usage: dict[str, float] = {}
    for period, (start, end) in intervals.items():
        scoped = [event for event in events if start <= event.timestamp < end]
        result = LoadResult(
            events=scoped,
            duplicates=0,
            tier_sources={},
            plan_types=set(),
            credit_samples=[],
            warnings=[],
        )
        aggregate = aggregate_total(result, options, label=period, rate_card=rate_card)
        usage[f"{period}.credits"] = aggregate.costs.adjusted_credits
        usage[f"{period}.api_dollars"] = aggregate.costs.api_dollars
        usage[f"{period}.tokens"] = float(aggregate.totals.total_tokens)
    return usage


def _severity_style(severity: str) -> str:
    if severity == SEVERITY_BREACH:
        return "[red]breach[/red]"
    if severity == SEVERITY_WARN:
        return "[yellow]warn[/yellow]"
    return "[green]ok[/green]"


@budgets_app.command("check")
def budgets_check(
    config: ConfigOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    rates_file: RatesFileOpt = None,
    tier_overrides: TierOverridesOpt = None,
    service_tier: ServiceTierOpt = "auto",
    pricing_mode: PricingModeOpt = "model",
    output_format: FormatOpt = "table",
) -> None:
    """Evaluate `[budgets]` from .codex-meter.toml against the current window."""
    if output_format not in {"table", "json"}:
        raise _exit_error("--format must be one of: table, json")
    try:
        loaded = load_config(config) if config else load_config()
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    raw = loaded.get("budgets") or {}
    try:
        budget_list: list[Budget] = parse_budgets_table(raw if isinstance(raw, dict) else {})
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    if not budget_list:
        console.print(
            "[dim]No budgets defined. Add a [budgets] table to .codex-meter.toml. "
            "Example: daily_credits = 25000.[/dim]"
        )
        raise typer.Exit(0)

    try:
        options = build_options(
            days=31.0,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
            tier_overrides=tier_overrides,
            service_tier=service_tier,
            pricing_mode=pricing_mode,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    result = load_usage(options)
    rate_card = RateCard.load(options.rates_file, options.pricing_mode)
    now = dt.datetime.now(tz=local_timezone())
    usage = _usage_for_periods(result.events, options, rate_card, now)
    alerts: list[BudgetAlert] = evaluate_budgets(budget_list, usage)
    worst = max_severity(alerts)

    if output_format == "json":
        import json as _json

        typer.echo(
            _json.dumps(
                {
                    "alerts": [
                        {
                            "period": alert.budget.period,
                            "metric": alert.budget.metric,
                            "limit": alert.budget.limit,
                            "warn_at": alert.budget.warn_at,
                            "used": alert.used,
                            "used_percent": alert.used_percent,
                            "severity": alert.severity,
                        }
                        for alert in alerts
                    ],
                    "max_severity": worst,
                },
                indent=2,
            )
        )
        raise typer.Exit(SEVERITY_EXIT_CODE[worst])

    from rich.table import Table

    console.print("[bold]Codex Meter - Budgets[/bold]")
    table = Table()
    table.add_column("Period")
    table.add_column("Metric")
    table.add_column("Used", justify="right")
    table.add_column("Limit", justify="right")
    table.add_column("%", justify="right")
    table.add_column("Status")
    for alert in alerts:
        table.add_row(
            alert.budget.period,
            alert.budget.metric,
            f"{alert.used:,.2f}",
            f"{alert.budget.limit:,.2f}",
            f"{alert.used_percent:,.1f}%",
            _severity_style(alert.severity),
        )
    console.print(table)
    console.print(f"Max severity: {_severity_style(worst)}")
    raise typer.Exit(SEVERITY_EXIT_CODE[worst])


@app.command()
def live(
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    tier_overrides: TierOverridesOpt = None,
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    default_model: DefaultModelOpt = "gpt-5.5",
    interval: Annotated[
        float,
        typer.Option("--interval", "-i", min=0.5, help="Refresh seconds. Default 2."),
    ] = 2.0,
) -> None:
    """Live TUI: today's usage, 5h + weekly window countdowns, burn rate."""
    try:
        options = build_options(
            days=7,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
            tier_overrides=tier_overrides,
            service_tier=service_tier,
            unknown_service_tier=unknown_service_tier,
            default_model=default_model,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    run_live(options, interval=interval)
