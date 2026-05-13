from __future__ import annotations

import calendar
import csv
import datetime as dt
import io
import json
import subprocess  # nosec
import sys
import time
from collections.abc import Callable
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import click
import typer
from rich.console import Console
from rich.table import Table

from caliper import __version__
from caliper.aggregation import (
    aggregate_daily,
    aggregate_daily_instances,
    aggregate_model_mode,
    aggregate_monthly,
    aggregate_overview_windows,
    aggregate_projects,
    aggregate_sessions,
    aggregate_total,
    aggregate_vendors,
    aggregate_weekly,
)
from caliper.arbitrage import explain as explain_arbitrage
from caliper.arbitrage import suggest as suggest_arbitrage
from caliper.budgets import (
    SEVERITY_BREACH,
    SEVERITY_EXIT_CODE,
    SEVERITY_WARN,
    alert_records,
    max_severity,
    parse_budgets_table,
    usage_for_periods,
)
from caliper.budgets import (
    evaluate as evaluate_budgets,
)
from caliper.config import build_options, load_config
from caliper.evidence import evidence_metadata, evidence_rows
from caliper.exporters import (
    ReceiptInputs,
    month_bounds,
    render_grafana_dashboard,
    render_receipt_html,
    render_receipt_markdown,
)
from caliper.forecasts import project as project_forecast
from caliper.git import commit_for_sha, commits_for_revspec, gh_pr_commit_shas, local_pull_ref
from caliper.health import (
    HEALTH_EXIT_CODES,
    HEALTH_STATUS_STYLES,
    build_health_report,
    parser_warning_summary,
    rate_card_age_days,
    worst_health_status,
)
from caliper.humanize import short_table_label
from caliper.insights import build_insights, insights_payload, render_insights_markdown
from caliper.intervals import parse_interval
from caliper.live import run_live
from caliper.models import (
    Aggregate,
    LoadResult,
    Rates,
    RuntimeOptions,
)
from caliper.output import (
    amount_fields,
    json_dumps,
    json_dumps_enveloped,
    records_to_csv,
    records_to_markdown,
    with_caliper_envelope,
)
from caliper.parser import load_usage
from caliper.pricing import (
    MODEL_CARDS,
    PRICING_SOURCES,
    RateCard,
    available_model_names,
    load_rate_card,
    pricing_catalog_status,
)
from caliper.pricing_catalog import (
    catalog_model_records,
    fetch_pricing_catalog,
    load_cached_catalog,
    pricing_catalog_path,
    replace_pricing_catalog_cache,
)
from caliper.prom_snapshot import build_prometheus_snapshot
from caliper.rate_audit import (
    rate_card_payload,
    rate_card_records,
)
from caliper.render import format_int, pricing_status, pricing_warnings, render, render_limits
from caliper.scenarios import (
    aggregate_interval,
    aggregate_interval_by_vendor,
    amount_delta,
    build_whatif_report,
    interval_summary,
    sparse_comparison_warning,
)
from caliper.schemas import export_schema, validate_json
from caliper.statusline import (
    build_statusline_snapshot,
    render_statusline_text,
    statusline_payload,
)
from caliper.taxonomy import taxonomy_records
from caliper.timeutil import iso_z, local_timezone, window_label
from caliper.vendors import vendor_summaries

app = typer.Typer(
    help=(
        "Caliper: the cost layer for AI-assisted development.\n\n"
        "Reads local OpenAI Codex CLI, Claude Code, Cursor, and Aider logs. "
        "Joins them into one event shape. Prints what each PR, commit, and "
        "project cost. Offline by default. No login. No upload.\n\n"
        "Start with: caliper overview"
    ),
    no_args_is_help=False,
)
console = Console()

OUTPUT_FORMATS = ("table", "json", "csv", "markdown", "compat-json")

SinceOpt = Annotated[
    str | None,
    typer.Option(
        "--window-start",
        "--since",
        "-s",
        help="Inclusive report window start. Supports YYYY-MM-DD, YYYYMMDD, or ISO.",
    ),
]
UntilOpt = Annotated[
    str | None,
    typer.Option(
        "--window-end",
        "--until",
        "-u",
        help="Exclusive report window end. Defaults to now.",
    ),
]
DaysOpt = Annotated[
    float | None,
    typer.Option("--lookback-days", "--days", help="Rolling day window before --window-end."),
]
TimezoneOpt = Annotated[
    str,
    typer.Option(
        "--grouping-timezone",
        "--timezone",
        "-z",
        help="Timezone used for report grouping. Use local or an IANA name.",
    ),
]
SessionRootOpt = Annotated[
    Path | None,
    typer.Option("--codex-session-root", "--session-root", help="Codex session JSONL root."),
]
StateDbOpt = Annotated[
    Path | None,
    typer.Option("--codex-state-db", "--state-db", help="Codex state_5.sqlite path."),
]
CodexConfigOpt = Annotated[
    Path | None,
    typer.Option("--codex-config-file", "--codex-config", help="Codex config.toml path."),
]
ConfigOpt = Annotated[
    Path | None,
    typer.Option("--caliper-config-file", "--config", help="Caliper config TOML path."),
]
PricingModeOpt = Annotated[
    str,
    typer.Option(
        "--pricing-estimation-mode",
        "--pricing-mode",
        help="Pricing mode: model or flat.",
    ),
]
PricingSourceOpt = Annotated[
    str,
    typer.Option(
        "--pricing-catalog-source",
        "--pricing-source",
        help="Pricing catalog source: auto, embedded, litellm, openrouter, portkey, or codex.",
    ),
]
PricingCacheTtlOpt = Annotated[
    int,
    typer.Option(
        "--pricing-catalog-cache-ttl-hours",
        "--pricing-cache-ttl-hours",
        help="Hours before a cached pricing catalog is considered stale.",
    ),
]
ServiceTierOpt = Annotated[
    str,
    typer.Option("--codex-service-tier", "--service-tier", help="Codex service tier override."),
]
UnknownTierOpt = Annotated[
    str,
    typer.Option(
        "--assumed-service-tier",
        "--unknown-service-tier",
        help="Tier to assume when logs and config do not identify one.",
    ),
]
TierOverridesOpt = Annotated[
    Path | None,
    typer.Option(
        "--service-tier-overrides-file",
        "--tier-overrides",
        help="JSON file with per-session or per-path service-tier overrides.",
    ),
]
RatesFileOpt = Annotated[
    Path | None,
    typer.Option("--rate-card-file", "--rates-file", help="Local rate-card override JSON file."),
]
NoDedupeOpt = Annotated[
    bool,
    typer.Option("--disable-deduplication", "--no-dedupe", help="Keep duplicate usage events."),
]
NoParseCacheOpt = Annotated[
    bool,
    typer.Option(
        "--disable-parse-cache",
        "--no-parse-cache",
        help="Reparse source logs without the sidecar cache.",
    ),
]
DefaultModelOpt = Annotated[
    str,
    typer.Option("--fallback-model", "--default-model", help="Model assumed when logs omit one."),
]
ShowPromptsOpt = Annotated[
    bool,
    typer.Option(
        "--include-sensitive-prompts",
        "--show-prompts",
        help="Include prompt text and full prompt-derived labels in output.",
    ),
]
OfflineOpt = Annotated[
    bool,
    typer.Option(
        "--pricing-offline-only/--allow-pricing-network",
        "--offline/--no-offline",
        help="Use only local pricing data, or allow explicit pricing network refresh paths.",
    ),
]
CompactOpt = Annotated[bool, typer.Option("--compact-output", "--compact")]
WidthOpt = Annotated[
    int | None,
    typer.Option("--table-width", "--width", help="Table width override."),
]
TopThreadsOpt = Annotated[
    int,
    typer.Option("--row-limit", "--top", "--top-threads", help="Limit grouped output rows."),
]
RateLimitSampleLimitOpt = Annotated[
    int,
    typer.Option(
        "--rate-limit-sample-limit",
        help="Recent rate-limit samples to include in grouped JSON reports.",
    ),
]
IncludeAllRateLimitSamplesOpt = Annotated[
    bool,
    typer.Option(
        "--include-all-rate-limit-samples",
        help="Include every rate-limit sample in grouped JSON reports.",
    ),
]
FormatOpt = Annotated[
    str,
    typer.Option(
        "--output-format",
        "--format",
        "-f",
        help="table, json, csv, markdown, or compat-json.",
    ),
]
StatuslineFormatOpt = Annotated[
    str,
    typer.Option("--output-format", "--format", "-f", help="text or json."),
]
OutputOpt = Annotated[
    Path | None,
    typer.Option("--output-file", "--output", help="Write output to a file."),
]
OrderOpt = Annotated[
    str,
    typer.Option("--sort-order", "--order", "-o", help="Sort order: asc or desc."),
]
StartOfWeekOpt = Annotated[
    str,
    typer.Option(
        "--week-start-day",
        "--start-of-week",
        "-w",
        help="Day to start weekly reports on.",
        case_sensitive=False,
    ),
]
ProjectOpt = Annotated[
    str | None,
    typer.Option("--project-filter", "--project", "-p", help="Filter by project path or label."),
]
InstancesOpt = Annotated[
    bool,
    typer.Option(
        "--split-by-project-instance",
        "--instances",
        "-i",
        help="Split daily rows by project instance.",
    ),
]
BreakdownOpt = Annotated[
    bool,
    typer.Option(
        "--include-model-breakdown",
        "--breakdown",
        "-b",
        help="Show per-model breakdown rows where supported.",
    ),
]
CostModeOpt = Annotated[
    str,
    typer.Option(
        "--vendor-cost-mode",
        "--cost-mode",
        "-m",
        help="Vendor cost mode: auto, calculate, or display.",
    ),
]
VendorOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--include-vendor",
        "--vendor",
        help="Vendor to include. Repeatable; default all.",
    ),
]

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
    "pricing_source",
    "pricing_cache_ttl_hours",
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
    "rate_limit_sample_limit",
    "include_all_rate_limit_samples",
    "order",
    "start_of_week",
    "project",
    "instances",
    "breakdown",
    "cost_mode",
    "vendors",
)
ROOT_OPTION_DEFAULTS: dict[str, Any] = {
    "output_format": "table",
    "output": None,
    "session_root": None,
    "state_db": None,
    "codex_config": None,
    "config": None,
    "pricing_mode": "model",
    "pricing_source": "auto",
    "pricing_cache_ttl_hours": 24,
    "service_tier": "auto",
    "unknown_service_tier": "current-config",
    "tier_overrides": None,
    "rates_file": None,
    "no_dedupe": False,
    "no_parse_cache": False,
    "default_model": "gpt-5.5",
    "compact": False,
    "width": None,
    "rate_limit_sample_limit": 100,
    "include_all_rate_limit_samples": False,
    "vendors": None,
}


def _exit_error(message: str) -> typer.Exit:
    console.print(f"[red]error:[/red] {message}")
    return typer.Exit(2)


def _validate_format(output_format: str) -> None:
    if output_format not in OUTPUT_FORMATS:
        raise _exit_error(f"--output-format must be one of: {', '.join(OUTPUT_FORMATS)}")


def _with_parent_options(values: dict) -> dict:
    merged = dict(values)
    ctx = click.get_current_context(silent=True)
    parent = ctx.parent if ctx else None
    if parent is None:
        return merged
    for key, default in ROOT_OPTION_DEFAULTS.items():
        parent_value = parent.params.get(key, default)
        if parent_value == default:
            continue
        current = merged.get(key, default)
        if current == default:
            merged[key] = parent_value
    return merged


def _options(values: dict) -> RuntimeOptions:
    values = _with_parent_options(values)
    kwargs = {key: values[key] for key in OPTION_KEYS if key in values}
    try:
        return build_options(**kwargs)
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc


def _run_grouped(name: str, rows_fn: RowsFn, values: dict) -> None:
    values = _with_parent_options(values)
    _validate_format(values["output_format"])
    options = _options(values)
    result = load_usage(options)
    if name == "daily" and options.instances:
        rows_fn = aggregate_daily_instances
    rows = rows_fn(result, options)
    if options.order == "desc" and name in {"daily", "weekly", "monthly"}:
        rows = list(reversed(rows))
    if options.top_threads:
        rows = rows[: options.top_threads]
    if values["output_format"] == "compat-json":
        text = _compat_json(name, rows, result, options)
        if values["output"]:
            values["output"].expanduser().write_text(text)
        else:
            typer.echo(text, nl=False)
        return
    render(result, options, rows, name, values["output_format"], values["output"])


def _run_session_id(values: dict, session_id: str) -> None:
    values = _with_parent_options(values)
    _validate_format(values["output_format"])
    options = _options(values)
    result = load_usage(options)
    scoped = LoadResult(
        events=[event for event in result.events if event.session_id == session_id],
        duplicates=0,
        tier_sources=result.tier_sources,
        plan_types=result.plan_types,
        credit_samples=[],
        warnings=result.warnings,
        parser_issues=result.parser_issues,
        vendor_stats=result.vendor_stats,
    )
    rows = aggregate_sessions(scoped, options)
    if values["output_format"] == "compat-json":
        text = _compat_session_id_json(session_id, scoped, options)
    else:
        text = render_json_text(scoped, options, rows, "session", values["output_format"])
    if values["output"]:
        values["output"].expanduser().write_text(text)
    else:
        typer.echo(text, nl=False)


def render_json_text(
    result: LoadResult,
    options: RuntimeOptions,
    rows: list[Aggregate],
    name: str,
    output_format: str,
) -> str:
    if output_format == "json":
        from caliper.render import render_json

        return render_json(
            result,
            options,
            rows,
            name,
            rate_card=load_rate_card(options),
        )
    if output_format == "csv":
        from caliper.render import render_csv

        return render_csv(rows, options.show_prompts)
    if output_format == "markdown":
        from caliper.render import render_markdown

        return render_markdown(rows, options.show_prompts)
    from caliper.render import render_table

    return render_table(
        result,
        options,
        rows,
        f"Caliper - {name.title()}",
        rate_card=load_rate_card(options),
    )


def _compat_json(
    name: str, rows: list[Aggregate], result: LoadResult, options: RuntimeOptions
) -> str:
    total = aggregate_total(
        result,
        options,
        rate_card=load_rate_card(options),
    )
    if name == "daily" and options.instances:
        projects: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            date, project = _split_instance_key(row.key)
            item = _compat_row("daily", row, options)
            item["date"] = date
            projects.setdefault(project, []).append(item)
        return json.dumps({"projects": projects, "totals": _compat_totals(total)}, indent=2) + "\n"
    payload_rows = [_compat_row(name, row, options) for row in rows]
    key = {"daily": "daily", "weekly": "weekly", "monthly": "monthly", "session": "sessions"}.get(
        name, name
    )
    return json.dumps({key: payload_rows, "totals": _compat_totals(total)}, indent=2) + "\n"


def _compat_session_id_json(session_id: str, result: LoadResult, options: RuntimeOptions) -> str:
    rate_card = load_rate_card(options)
    total = aggregate_total(result, options, rate_card=rate_card)
    entries = []
    for event in sorted(result.events, key=lambda item: item.timestamp):
        entries.append(
            {
                "timestamp": iso_z(event.timestamp),
                "inputTokens": event.usage.uncached_input_tokens,
                "outputTokens": event.usage.output_tokens,
                "cacheCreationTokens": (
                    event.usage.cache_creation_input_tokens
                    + event.usage.cache_creation_input_1h_tokens
                ),
                "cacheReadTokens": event.usage.cache_read_input_tokens,
                "model": event.raw_model or event.model or "unknown",
                "costUSD": 0,
            }
        )
    return (
        json.dumps(
            {
                "sessionId": session_id,
                "totalCost": float(total.costs.api_dollars),
                "totalTokens": total.totals.total_tokens,
                "entries": entries,
            },
            indent=2,
        )
        + "\n"
    )


def _split_instance_key(key: str) -> tuple[str, str]:
    if "\0" not in key:
        return key, "unknown"
    date, project = key.split("\0", 1)
    return date, project or "unknown"


def _compat_row(name: str, row: Aggregate, options: RuntimeOptions) -> dict[str, Any]:
    key_name = {
        "daily": "date",
        "weekly": "week",
        "monthly": "month",
        "session": "sessionId",
    }.get(name, "key")
    item = {key_name: row.key, **_compat_totals(row)}
    if name == "session":
        item["lastActivity"] = (
            row.last_seen.astimezone(_timezone(options)).strftime("%Y-%m-%d")
            if row.last_seen
            else ""
        )
        item["projectPath"] = next(iter(sorted(row.project_paths)), "Unknown Project")
    item["modelsUsed"] = sorted(row.models)
    item["modelBreakdowns"] = [
        _compat_model_breakdown(model) for model in row.model_breakdowns.values()
    ]
    return item


def _compat_totals(row: Aggregate) -> dict[str, Any]:
    return {
        "inputTokens": row.totals.uncached_input_tokens,
        "outputTokens": row.totals.output_tokens,
        "cacheCreationTokens": (
            row.totals.cache_creation_input_tokens + row.totals.cache_creation_input_1h_tokens
        ),
        "cacheReadTokens": row.totals.cache_read_input_tokens,
        "totalTokens": row.totals.total_tokens,
        "totalCost": float(row.costs.api_dollars),
    }


def _compat_model_breakdown(row) -> dict[str, Any]:
    return {
        "modelName": row.model,
        "inputTokens": row.totals.uncached_input_tokens,
        "outputTokens": row.totals.output_tokens,
        "cacheCreationTokens": (
            row.totals.cache_creation_input_tokens + row.totals.cache_creation_input_1h_tokens
        ),
        "cacheReadTokens": row.totals.cache_read_input_tokens,
        "cost": float(row.costs.api_dollars),
    }


def _timezone(options: RuntimeOptions) -> dt.tzinfo:
    from caliper.timeutil import load_timezone

    return load_timezone(options.timezone)


def version_callback(value: bool) -> None:
    if value:
        console.print(_version_label())
        raise typer.Exit()


def _version_label() -> str:
    checked = max(source.checked for source in PRICING_SOURCES)
    try:
        completed = subprocess.run(  # noqa: S603 # nosec
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
        typer.Option(
            "--show-version",
            "--version",
            "-v",
            callback=version_callback,
            help="Show version and exit.",
        ),
    ] = False,
    output_format: FormatOpt = "table",
    output: OutputOpt = None,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    pricing_mode: PricingModeOpt = "model",
    pricing_source: PricingSourceOpt = "auto",
    pricing_cache_ttl_hours: PricingCacheTtlOpt = 24,
    service_tier: ServiceTierOpt = "auto",
    unknown_service_tier: UnknownTierOpt = "current-config",
    tier_overrides: TierOverridesOpt = None,
    rates_file: RatesFileOpt = None,
    no_dedupe: NoDedupeOpt = False,
    no_parse_cache: NoParseCacheOpt = False,
    default_model: DefaultModelOpt = "gpt-5.5",
    compact: CompactOpt = False,
    width: WidthOpt = None,
    rate_limit_sample_limit: RateLimitSampleLimitOpt = 100,
    include_all_rate_limit_samples: IncludeAllRateLimitSamplesOpt = False,
    vendors: VendorOpt = None,
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
    with _interactive_status("Loading 90 days of usage...", output_format, values["output"]):
        longest_result = load_usage(longest_options)
    rate_card = load_rate_card(longest_options)
    with _interactive_status("Aggregating overview windows...", output_format, values["output"]):
        rows, total = aggregate_overview_windows(
            longest_result,
            longest_options,
            [(f"Last {days} days", now - dt.timedelta(days=days)) for days in (7, 30, 90)],
            rate_card=rate_card,
            detailed=output_format == "json",
        )
    render(
        longest_result,
        longest_options,
        rows,
        "overview",
        output_format,
        values["output"],
        total=total,
    )


def _interactive_status(message: str, output_format: str, output: Path | None):
    if output is not None or output_format != "table" or not sys.stderr.isatty():
        return nullcontext()
    Console(stderr=True).print(f"[dim]{message}[/dim]")
    return nullcontext()


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
    rate_limit_sample_limit: RateLimitSampleLimitOpt = 100,
    include_all_rate_limit_samples: IncludeAllRateLimitSamplesOpt = False,
    vendors: VendorOpt = None,
) -> None:
    """Print the rolling 7, 30, and 90 day cost summary. Start here."""
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
    top_threads: TopThreadsOpt = 0,
    rate_limit_sample_limit: RateLimitSampleLimitOpt = 100,
    include_all_rate_limit_samples: IncludeAllRateLimitSamplesOpt = False,
    order: OrderOpt = "asc",
    project: ProjectOpt = None,
    instances: InstancesOpt = False,
    breakdown: BreakdownOpt = False,
    cost_mode: CostModeOpt = "auto",
    vendors: VendorOpt = None,
) -> None:
    """Print token and cost rollups grouped by day."""
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
    top_threads: TopThreadsOpt = 0,
    rate_limit_sample_limit: RateLimitSampleLimitOpt = 100,
    include_all_rate_limit_samples: IncludeAllRateLimitSamplesOpt = False,
    order: OrderOpt = "asc",
    start_of_week: StartOfWeekOpt = "sunday",
    project: ProjectOpt = None,
    breakdown: BreakdownOpt = False,
    cost_mode: CostModeOpt = "auto",
    vendors: VendorOpt = None,
) -> None:
    """Print token and cost rollups grouped by week."""
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
    top_threads: TopThreadsOpt = 0,
    rate_limit_sample_limit: RateLimitSampleLimitOpt = 100,
    include_all_rate_limit_samples: IncludeAllRateLimitSamplesOpt = False,
    order: OrderOpt = "asc",
    project: ProjectOpt = None,
    breakdown: BreakdownOpt = False,
    cost_mode: CostModeOpt = "auto",
    vendors: VendorOpt = None,
) -> None:
    """Print token and cost rollups grouped by month."""
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
    top_threads: TopThreadsOpt = 0,
    rate_limit_sample_limit: RateLimitSampleLimitOpt = 100,
    include_all_rate_limit_samples: IncludeAllRateLimitSamplesOpt = False,
    project: ProjectOpt = None,
    breakdown: BreakdownOpt = False,
    cost_mode: CostModeOpt = "auto",
    id: Annotated[
        str | None,
        typer.Option("--session-id", "--id", "-i", help="Load one session id."),
    ] = None,
    vendors: VendorOpt = None,
) -> None:
    """Print one row per session with tokens, cost, and model breakdown."""
    if id:
        locals_values = locals()
        locals_values["project"] = id
        # Session id lookup is implemented by filtering grouped rows after load,
        # while project remains available to the loader for project filtering.
        result = _run_session_id(locals_values, id)
        return result
    _run_grouped("session", aggregate_sessions, locals())


@app.command()
def blocks(
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
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    top_threads: TopThreadsOpt = 0,
    order: OrderOpt = "asc",
    project: ProjectOpt = None,
    cost_mode: CostModeOpt = "auto",
    active: Annotated[
        bool,
        typer.Option("--only-active-block", "--active", "-a", help="Show only active block."),
    ] = False,
    recent: Annotated[
        bool,
        typer.Option("--recent-blocks", "--recent", "-r", help="Show blocks from the last 3 days."),
    ] = False,
    token_limit: Annotated[
        str | None,
        typer.Option("--block-token-limit", "--token-limit", "-t", help='Token limit, or "max".'),
    ] = None,
    session_length: Annotated[
        float,
        typer.Option(
            "--block-duration-hours",
            "--session-length",
            "-n",
            help="Session block duration in hours.",
        ),
    ] = 5.0,
    vendors: VendorOpt = None,
) -> None:
    """Print session billing blocks. Use --active to see the current block only."""
    from caliper.blocks import block_payload, build_blocks, filter_recent_blocks

    _validate_format(output_format)
    options = _options(locals())
    result = load_usage(options)
    rate_card = load_rate_card(options)
    rows = build_blocks(result, options, rate_card, session_length_hours=session_length)
    if recent:
        rows = filter_recent_blocks(rows)
    if active:
        rows = [row for row in rows if row.is_active]
    if options.order == "desc":
        rows = list(reversed(rows))
    if options.top_threads:
        rows = rows[: options.top_threads]
    parsed_token_limit = _parse_token_limit(token_limit)
    payload = {"blocks": [block_payload(row, parsed_token_limit) for row in rows]}
    if output_format in {"json", "compat-json"}:
        text = json.dumps(payload, indent=2) + "\n"
    elif output_format == "csv":
        text = records_to_csv(payload["blocks"])
    elif output_format == "markdown":
        text = records_to_markdown(payload["blocks"])
    else:
        text = _blocks_table(payload["blocks"], options)
    if output:
        output.expanduser().write_text(text)
    else:
        typer.echo(text, nl=False)


def _parse_token_limit(value: str | None) -> int | None:
    if value is None or value == "" or value == "max":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise _exit_error("--token-limit must be an integer or max") from exc
    if parsed <= 0:
        raise _exit_error("--token-limit must be greater than 0")
    return parsed


def _blocks_table(rows: list[dict[str, Any]], options: RuntimeOptions) -> str:
    buffer = io.StringIO()
    local_console = Console(file=buffer, width=options.width or 120, _environ={})
    local_console.print("[bold]Caliper - Blocks[/bold]")
    table = Table(show_lines=False, expand=not options.compact)
    table.add_column("Start")
    table.add_column("Status")
    table.add_column("Models")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    for row in rows:
        status = "gap" if row["isGap"] else "active" if row["isActive"] else ""
        table.add_row(
            str(row["startTime"]),
            status,
            ", ".join(row["models"]),
            format_int(int(row["totalTokens"])),
            f"${float(row['costUSD']):,.2f}",
        )
    local_console.print(table)
    return buffer.getvalue()


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
    top_threads: TopThreadsOpt = 0,
    rate_limit_sample_limit: RateLimitSampleLimitOpt = 100,
    include_all_rate_limit_samples: IncludeAllRateLimitSamplesOpt = False,
    order: OrderOpt = "asc",
    project: ProjectOpt = None,
    breakdown: BreakdownOpt = False,
    cost_mode: CostModeOpt = "auto",
    vendors: VendorOpt = None,
) -> None:
    """Print cost per project (working directory). Answers: which repo cost what."""
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
    top_threads: TopThreadsOpt = 0,
    rate_limit_sample_limit: RateLimitSampleLimitOpt = 100,
    include_all_rate_limit_samples: IncludeAllRateLimitSamplesOpt = False,
    order: OrderOpt = "asc",
    project: ProjectOpt = None,
    breakdown: BreakdownOpt = False,
    cost_mode: CostModeOpt = "auto",
    vendors: VendorOpt = None,
    by: Annotated[str, typer.Option("--group-by", "--by", help="model or vendor.")] = "model",
) -> None:
    """Print cost per model and service tier. Answers: which model cost what."""
    if by not in {"model", "vendor"}:
        raise _exit_error("--by must be one of: model, vendor")
    rows_fn = aggregate_vendors if by == "vendor" else aggregate_model_mode
    _run_grouped("models", rows_fn, locals())


@app.command()
def evidence(
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
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    width: WidthOpt = None,
    vendors: VendorOpt = None,
) -> None:
    """Show where each event came from and how confident the parser is in it."""
    _validate_format(output_format)
    options = _options(locals())
    result = load_usage(options)
    rate_card = load_rate_card(options)
    total = aggregate_total(result, options, rate_card=rate_card)
    rows = evidence_rows(result, total)
    payload = {
        "command": "evidence",
        "window": {
            "start": iso_z(options.start),
            "end": iso_z(options.end),
            "label": window_label(options.start, options.end, options.timezone),
            "timezone": options.timezone,
        },
        "totals": {
            "events": total.totals.events,
            "input_tokens": total.totals.input_tokens,
            "cached_input_tokens": total.totals.cached_input_tokens,
            "output_tokens": total.totals.output_tokens,
            "total_tokens": total.totals.total_tokens,
            "api_dollars": str(total.costs.api_dollars),
            "credits": str(total.costs.adjusted_credits),
        },
        "evidence": evidence_metadata(result, total),
        "rows": rows,
        "warnings": result.warnings,
    }
    text = _evidence_text(output_format, payload, rows, options)
    if output:
        output.expanduser().write_text(text)
    else:
        typer.echo(text, nl=False)


def _evidence_text(
    output_format: str,
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    options: RuntimeOptions,
) -> str:
    if output_format == "json":
        return json_dumps_enveloped(payload) + "\n"
    if output_format == "csv":
        return records_to_csv(rows)
    if output_format == "markdown":
        return records_to_markdown(rows)

    buffer = io.StringIO()
    local_console = Console(file=buffer, width=options.width or 120, _environ={})
    local_console.print("[bold]Caliper - Evidence[/bold]")
    local_console.print(f"Overall: {payload['evidence']['overall']}")
    table = Table(show_lines=False, expand=not options.compact)
    table.add_column("Section")
    table.add_column("Name")
    table.add_column("Grade")
    table.add_column("Events", justify="right")
    table.add_column("Reason")
    for row in rows:
        table.add_row(
            str(row["section"]),
            str(row["name"]),
            str(row["grade"]),
            format_int(int(row["events"])),
            str(row["reason"]),
        )
    local_console.print(table)
    return buffer.getvalue()


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
    vendors: VendorOpt = None,
) -> None:
    """Show recent rate-limit hits and credit-cap samples by window."""
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
    vendors: VendorOpt = None,
) -> None:
    """Call out cache reuse, tier confidence, and project concentration signals."""
    if output_format not in {"table", "json", "markdown"}:
        raise _exit_error("--output-format must be one of: table, json, markdown")
    options = _options(locals())
    result = load_usage(options)
    card = load_rate_card(options)
    items = build_insights(result, options, rate_card=card)[: options.top_threads]
    if output_format == "json":
        text = json_dumps_enveloped(insights_payload(items)) + "\n"
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
    local_console.print("[bold]Caliper - Insights[/bold]")
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
    n: Annotated[
        int,
        typer.Option("--event-limit", "--n", min=1, help="Number of recent records."),
    ] = 20,
    by: Annotated[
        str,
        typer.Option("--tail-grouping", "--by", help="event or session."),
    ] = "event",
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
    vendors: VendorOpt = None,
) -> None:
    """Print the most recent usage events or sessions. Use --by session to group."""
    del top_threads
    if by not in {"event", "session"}:
        raise _exit_error("--by must be one of: event, session")
    if output_format not in {"table", "json", "csv"}:
        raise _exit_error("--output-format must be one of: table, json, csv")
    options = _options(locals() | {"top_threads": n})
    result = load_usage(options)
    rows = _recent_tail_rows(result, n, by)
    if output_format == "json":
        text = json_dumps_enveloped({"by": by, f"{by}s": rows}) + "\n"
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
    local_console.print(f"[bold]Caliper - Recent {by.title()}s[/bold]")
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


@app.command()
def doctor(
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    vendors: VendorOpt = None,
    output_format: Annotated[
        str,
        typer.Option("--output-format", "--format", "-f", help="table, json, csv, or markdown."),
    ] = "table",
) -> None:
    """Verify your local setup: data paths, rate-card age, clock skew, and tooling.

    Run this first if anything looks wrong. Exits 0 ok, 1 warn, 2 fail."""
    _validate_format(output_format)
    try:
        options = build_options(
            days=7.0,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    files = list(options.session_root.glob("**/*.jsonl")) if options.session_root.exists() else []
    vendor_file_count = _discovered_vendor_file_count(options)
    result = load_usage(options) if vendor_file_count else None
    checks = build_health_report(
        options=options,
        session_file_count=len(files),
        result=result,
    )
    worst = worst_health_status(checks)
    check_records = [check.to_record() for check in checks]

    if output_format == "json":
        typer.echo(
            json_dumps_enveloped(
                {
                    "checks": check_records,
                    "worst": worst,
                    "warning_summary": [
                        summary.to_record()
                        for summary in parser_warning_summary(
                            result.warnings if result else [],
                            result.parser_issues if result else [],
                        )
                    ],
                }
            )
        )
        raise typer.Exit(HEALTH_EXIT_CODES[worst])

    if output_format == "csv":
        typer.echo(
            records_to_csv(check_records),
            nl=False,
        )
        raise typer.Exit(HEALTH_EXIT_CODES[worst])

    if output_format == "markdown":
        typer.echo(
            records_to_markdown(check_records),
            nl=False,
        )
        raise typer.Exit(HEALTH_EXIT_CODES[worst])

    console.print("[bold]Caliper - Doctor[/bold]")
    table = Table(show_lines=False)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check in checks:
        style = HEALTH_STATUS_STYLES[check.status]
        table.add_row(check.label, f"[{style}]{check.status.upper()}[/{style}]", check.detail)
    console.print(table)
    console.print(
        f"Overall: [{HEALTH_STATUS_STYLES[worst]}]{worst.upper()}[/{HEALTH_STATUS_STYLES[worst]}]"
    )
    raise typer.Exit(HEALTH_EXIT_CODES[worst])


def _discovered_vendor_file_count(options: RuntimeOptions) -> int:
    from caliper.vendors import enabled_vendors

    total = 0
    for vendor in enabled_vendors(options):
        try:
            total += len(list(vendor.discover(options)))
        except OSError:
            continue
    return total


@app.command()
def init(
    path: Annotated[
        Path,
        typer.Option("--config-output-path", "--path", help="Target file path."),
    ] = Path(".caliper.toml"),
    force: Annotated[
        bool,
        typer.Option("--overwrite-existing", "--force", help="Overwrite an existing config."),
    ] = False,
) -> None:
    """Write a commented .caliper.toml next to your project. Safe to edit by hand."""
    if path.exists() and not force:
        raise _exit_error(f"{path} already exists. Pass --force to overwrite.")
    template = (
        "# Caliper config. Every key here can also be passed as a CLI flag.\n"
        "# The flag wins. Uncomment what you want to pin, leave the rest alone.\n"
        "\n"
        "# Rolling window for `caliper` and `caliper overview` in days.\n"
        "default_days = 30\n"
        '# timezone = "local"   # or an IANA zone, e.g. "America/Los_Angeles"\n'
        "\n"
        "# Where Codex CLI writes its sessions on this machine.\n"
        "# Override only if you moved Codex out of its default location.\n"
        '# session_root = "~/.codex/sessions"\n'
        '# state_db = "~/.codex/state_5.sqlite"\n'
        '# codex_config = "~/.codex/config.toml"\n'
        "\n"
        "# Pricing.\n"
        "# model = per-model rate card (recommended). flat = single fallback rate.\n"
        '# pricing_mode = "model"\n'
        '# pricing_source = "auto"          # auto, embedded, litellm, openrouter, portkey, codex\n'
        "# pricing_cache_ttl_hours = 24\n"
        "# Pin a local rate card to match an invoice exactly:\n"
        '# rates_file = "./rates.json"\n'
        "\n"
        "# Service-tier inference. The precedence chain is documented in the README.\n"
        'service_tier = "auto"\n'
        'unknown_service_tier = "current-config"\n'
        '# tier_overrides = "./tier-overrides.json"\n'
        "\n"
        "# Model assumed when a log line omits one.\n"
        'default_model = "gpt-5.5"\n'
        "\n"
        "# Output and privacy.\n"
        "# show_prompts = false   # never lets prompts or titles leak by default\n"
        "# offline = true         # network refresh is opt-in even with this false\n"
        "# compact = false\n"
        "# width = 140\n"
        "# top_threads = 10\n"
        "# rate_limit_sample_limit = 100\n"
        "# include_all_rate_limit_samples = false\n"
        "# no_dedupe = false\n"
        "# no_parse_cache = false\n"
        "\n"
        "# Budgets. Used by `caliper budgets check` to gate CI.\n"
        "# Severity: ok below warn_at, warn at warn_at (default 80%), breach at 100%.\n"
        "# Exit codes: 0 ok, 1 warn, 2 breach.\n"
        "[budgets]\n"
        "# daily_credits = 25000\n"
        "# weekly_credits = 100000\n"
        "# monthly_credits = 400000\n"
        "# weekly_api_dollars = 50.0\n"
        "# monthly_api_dollars = 500.0\n"
        "\n"
        "# Nested form when you want a custom warn threshold per period:\n"
        "# [budgets.monthly]\n"
        "# credits = 500000\n"
        "# warn_at = 0.7\n"
    )
    path.write_text(template)
    console.print(f"[green]Wrote[/green] {path}")
    console.print("[dim]Open it, set your budgets, then run `caliper budgets check`.[/dim]")


rates_app = typer.Typer(help="Show, refresh, and audit the pricing rate card.")
app.add_typer(rates_app, name="rates")

vendors_app = typer.Typer(help="List the AI coding tools Caliper found on disk.")
app.add_typer(vendors_app, name="vendors")

taxonomy_app = typer.Typer(help="Show the canonical model taxonomy Caliper uses.")
app.add_typer(taxonomy_app, name="taxonomy")

schema_app = typer.Typer(help="Export and validate Caliper JSON output schemas.")
app.add_typer(schema_app, name="schema")


@schema_app.command("export")
def schema_export(
    name: Annotated[
        str,
        typer.Option("--schema-name", "--name", help="Schema name."),
    ] = "usage_event",
    schema_format: Annotated[
        str,
        typer.Option("--output-format", "--format", "-f", help="json."),
    ] = "json",
    output: OutputOpt = None,
) -> None:
    """Print a Caliper JSON schema. Useful for validating exported reports."""
    if schema_format != "json":
        raise _exit_error("--output-format must be json")
    try:
        text = json_dumps(export_schema(name)) + "\n"
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    if output:
        output.expanduser().write_text(text)
    else:
        typer.echo(text, nl=False)


@schema_app.command("validate")
def schema_validate(
    path: Annotated[Path, typer.Argument(help="JSON file to validate.")],
    name: Annotated[
        str,
        typer.Option("--schema-name", "--name", help="Schema name."),
    ] = "usage_event",
) -> None:
    """Validate a JSON file against a Caliper schema. Exits non-zero on failure."""
    try:
        errors = validate_json(path, name)
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    if errors:
        for error in errors:
            console.print(f"[red]error:[/red] {error}")
        raise typer.Exit(2)
    console.print("[green]valid[/green]")


@taxonomy_app.command("show")
def taxonomy_show(output_format: FormatOpt = "table") -> None:
    """Print the canonical model taxonomy across all supported vendors."""
    _validate_format(output_format)
    records = taxonomy_records()
    if output_format == "json":
        typer.echo(json_dumps_enveloped({"models": records}))
        return
    if output_format == "csv":
        typer.echo(records_to_csv(records), nl=False)
        return
    if output_format == "markdown":
        typer.echo(records_to_markdown(records), nl=False)
        return
    console.print("[bold]Caliper - Model Taxonomy[/bold]")
    table = Table(show_lines=False)
    table.add_column("Vendor")
    table.add_column("Prefix")
    table.add_column("Canonical")
    table.add_column("Family")
    table.add_column("Tier")
    for record in records:
        table.add_row(
            record["vendor"],
            record["raw_prefix"],
            record["canonical"],
            record["family"],
            record["tier"],
        )
    console.print(table)


@vendors_app.command("list")
def vendors_list(
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    output_format: FormatOpt = "table",
    vendors: VendorOpt = None,
) -> None:
    """List supported vendors and whether Caliper found their logs on disk."""
    _validate_format(output_format)
    try:
        options = build_options(
            days=1.0,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    rows: list[dict[str, Any]] = [
        {
            "id": item.id,
            "label": item.label,
            "schema_version": item.schema_version,
            "files": item.files,
            "enabled": item.enabled,
        }
        for item in vendor_summaries(options)
    ]
    if output_format == "json":
        typer.echo(json_dumps_enveloped({"vendors": rows}))
        return
    if output_format == "csv":
        typer.echo(records_to_csv(rows), nl=False)
        return
    if output_format == "markdown":
        typer.echo(records_to_markdown(rows), nl=False)
        return
    console.print("[bold]Caliper - Vendors[/bold]")
    table = Table(show_lines=False)
    table.add_column("Vendor")
    table.add_column("Label")
    table.add_column("Schema")
    table.add_column("Files", justify="right")
    table.add_column("Enabled")
    for row in rows:
        table.add_row(
            row["id"],
            row["label"],
            str(row["schema_version"]),
            format_int(int(row["files"])),
            "yes" if row["enabled"] else "no",
        )
    console.print(table)


def _format_rates_label(rates: Rates | None) -> str:
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
        typer.Option("--output-format", "--format", "-f", help="table, json, csv, or markdown."),
    ] = "table",
    pricing_source: PricingSourceOpt = "auto",
    pricing_cache_ttl_hours: PricingCacheTtlOpt = 24,
    offline: OfflineOpt = True,
) -> None:
    """Show the active pricing rate card, its sources, and how old it is."""
    _validate_format(output_format)

    age = rate_card_age_days()
    payload = rate_card_payload(age)
    try:
        options = build_options(
            days=1.0,
            pricing_source=pricing_source,
            pricing_cache_ttl_hours=pricing_cache_ttl_hours,
            offline=offline,
        )
        card = load_rate_card(options)
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    payload["pricing_source"] = pricing_source
    payload["catalog"] = pricing_catalog_status(card)
    if output_format == "json":
        typer.echo(json_dumps_enveloped(payload))
        return
    if output_format in {"csv", "markdown"}:
        records = rate_card_records(payload)
        text = records_to_csv(records) if output_format == "csv" else records_to_markdown(records)
        typer.echo(text, nl=False)
        return

    console.print("[bold]Caliper - Rate Card[/bold]")
    console.print(
        f"Age: {age} days{'  [red](stale; consider refreshing)[/red]' if payload['stale'] else ''}"
    )
    catalog = payload["catalog"]
    console.print(
        "Catalog: "
        f"{catalog['source']} · {catalog['models']} models"
        f"{' · offline' if offline else ''}"
    )
    for source in PRICING_SOURCES:
        console.print(f"- {source.name} (checked {source.checked}): {source.url}")
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
        typer.Option(
            "--allow-live-pricing-network",
            "--allow-network",
            help="Fetch pricing pages over the network.",
        ),
    ] = False,
    pricing_source: PricingSourceOpt = "auto",
    output: OutputOpt = None,
) -> None:
    """Refresh the local pricing catalog. Offline by default. Pass --allow-network to fetch."""
    if not allow_network:
        raise _exit_error(
            "rates refresh needs --allow-network. The default path stays offline; pass "
            "--allow-network to fetch a live pricing catalog, or use --rates-file to "
            "override locally."
        )
    target = output or pricing_catalog_path()
    try:
        payload = fetch_pricing_catalog(pricing_source)
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    if payload.get("source") != "embedded" and not payload.get("models"):
        warnings = "; ".join(str(item) for item in payload.get("warnings", []) if item)
        detail = f": {warnings}" if warnings else ""
        raise _exit_error(f"no live pricing models were fetched{detail}")
    payload.setdefault("observed_models", payload.get("models", []))
    payload.setdefault("embedded_models", rate_card_payload(0)["models"])
    payload.setdefault("discrepancies", [])
    replace_pricing_catalog_cache(payload, target)
    console.print(f"[green]Wrote[/green] {target}")


@rates_app.command("catalog")
def rates_catalog(
    query: Annotated[
        str | None,
        typer.Option("--model-name-query", "--query", "-q", help="Filter model names."),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            "--pricing-provider",
            "--provider",
            "-p",
            help="Filter provider/source provider.",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--output-format", "--format", "-f", help="table, json, csv, or markdown."),
    ] = "table",
    allow_network: Annotated[
        bool,
        typer.Option(
            "--refresh-live-pricing-catalog",
            "--allow-network",
            help="Refresh stale/missing pricing catalog first.",
        ),
    ] = False,
    pricing_source: PricingSourceOpt = "auto",
    pricing_cache_ttl_hours: PricingCacheTtlOpt = 24,
) -> None:
    """Search the cached pricing catalog. Use --query to filter model names."""
    _validate_format(output_format)
    catalog = load_cached_catalog()
    if allow_network or not catalog.models:
        try:
            options = build_options(
                days=1.0,
                pricing_source=pricing_source,
                pricing_cache_ttl_hours=pricing_cache_ttl_hours,
                offline=not allow_network,
            )
            catalog = load_rate_card(options).pricing_catalog or catalog
        except ValueError as exc:
            raise _exit_error(str(exc)) from exc
    rows = catalog_model_records(catalog)
    if query:
        lowered = query.lower()
        rows = [row for row in rows if lowered in str(row["model"]).lower()]
    if provider:
        lowered_provider = provider.lower()
        rows = [row for row in rows if lowered_provider in str(row["provider"]).lower()]
    warnings = list(catalog.warnings)
    if not catalog.models:
        warnings.append(
            "no cached live pricing catalog; run `caliper rates refresh --allow-network` "
            "to populate it"
        )
    if output_format == "json":
        typer.echo(
            json_dumps_enveloped({"catalog": rows, "model_count": len(rows), "warnings": warnings})
        )
        return
    if output_format == "csv":
        typer.echo(records_to_csv(rows), nl=False)
        return
    if output_format == "markdown":
        typer.echo(records_to_markdown(rows), nl=False)
        return
    console.print("[bold]Caliper - Pricing Catalog[/bold]")
    for warning in warnings:
        console.print(f"[yellow]{warning}[/yellow]")
    table = Table(show_lines=False)
    table.add_column("Provider")
    table.add_column("Model")
    table.add_column("Input $/M", justify="right")
    table.add_column("Cached $/M", justify="right")
    table.add_column("Output $/M", justify="right")
    table.add_column("Context", justify="right")
    for row in rows[:100]:
        table.add_row(
            str(row["provider"]),
            str(row["model"]),
            str(row["api_input"]),
            str(row["api_cached_input"]),
            str(row["api_output"]),
            str(row["context_window"]),
        )
    console.print(table)
    if len(rows) > 100:
        console.print(f"[dim]Showing 100 of {len(rows):,} models; use --query to narrow.[/dim]")


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
    return [float(row.costs.adjusted_credits) for row in rows]


def _daily_api_dollar_series(events, options: RuntimeOptions, rate_card: RateCard) -> list[float]:
    result = LoadResult(
        events=list(events),
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
    )
    rows = aggregate_daily(result, options, rate_card=rate_card)
    return [float(row.costs.api_dollars) for row in rows]


def _sparkline(values: list[float]) -> str:
    if not values:
        return ""
    bars = "▁▂▃▄▅▆▇█"
    low = min(values)
    high = max(values)
    if high == low:
        return bars[0] * len(values)
    return "".join(bars[round((value - low) / (high - low) * (len(bars) - 1))] for value in values)


def _days_remaining_in_month(now: dt.datetime) -> int:
    last_day = calendar.monthrange(now.year, now.month)[1]
    return max(0, last_day - now.day)


@app.command()
def forecast(
    days: Annotated[
        int,
        typer.Option(
            "--forecast-history-days",
            "--days",
            min=1,
            max=180,
            help="Trailing day window analyzed.",
        ),
    ] = 14,
    cap: Annotated[
        float | None,
        typer.Option(
            "--monthly-credit-cap",
            "--cap",
            help="Plan credit cap. Compute days-to-depletion.",
        ),
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
    vendors: VendorOpt = None,
) -> None:
    """Project month-end credits with a ±1σ band. Pass --cap for days-to-depletion."""
    _validate_format(output_format)
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
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    result = load_usage(options)
    rate_card = load_rate_card(options)
    total = aggregate_total(result, options, rate_card=rate_card)
    status = pricing_status(total)
    warnings = pricing_warnings(total)
    daily = _daily_credit_series(result.events, options, rate_card)
    daily_dollars = _daily_api_dollar_series(result.events, options, rate_card)
    now = dt.datetime.now(tz=local_timezone())
    days_remaining = _days_remaining_in_month(now)
    projection = project_forecast(daily, days_remaining, unit="credits", cap=cap)
    dollar_projection = project_forecast(daily_dollars, days_remaining, unit="API $")
    sparkline = _sparkline(daily)

    forecast_payload = {
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
        "sparkline": sparkline,
        "projections": {
            "credits": {
                "linear_total": projection.linear_total,
                "ewma_total": projection.ewma_total,
                "daily_mean": projection.daily_mean,
            },
            "api_dollars": {
                "linear_total": dollar_projection.linear_total,
                "ewma_total": dollar_projection.ewma_total,
                "daily_mean": dollar_projection.daily_mean,
            },
        },
        "pricing_status": status,
        "pricing_warnings": warnings,
    }
    forecast_records = [
        {
            "unit": "credits",
            "daily_mean": f"{projection.daily_mean:.2f}",
            "linear_total": f"{projection.linear_total:.2f}",
            "ewma_total": f"{projection.ewma_total:.2f}",
            "sparkline": sparkline,
            "pricing_status": status,
        },
        {
            "unit": "api_dollars",
            "daily_mean": f"{dollar_projection.daily_mean:.2f}",
            "linear_total": f"{dollar_projection.linear_total:.2f}",
            "ewma_total": f"{dollar_projection.ewma_total:.2f}",
            "sparkline": sparkline,
            "pricing_status": status,
        },
    ]

    if output_format == "json":
        typer.echo(json_dumps_enveloped(forecast_payload))
        return

    if output_format == "csv":
        typer.echo(records_to_csv(forecast_records), nl=False)
        return

    if output_format == "markdown":
        typer.echo(records_to_markdown(forecast_records), nl=False)
        return

    console.print("[bold]Caliper - Forecast[/bold]")
    for warning in warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
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
    table.add_row("API $ projection", f"${dollar_projection.linear_total:,.2f}")
    table.add_row(
        "  ±1σ band",
        f"{projection.linear_low:,.2f} – {projection.linear_high:,.2f}",
    )
    table.add_row("EWMA projection", f"{projection.ewma_total:,.2f} {projection.unit}")
    table.add_row("Trend", sparkline or "no usage")
    if projection.cap is not None and projection.days_to_cap is not None:
        table.add_row("Plan cap", f"{projection.cap:,.2f} {projection.unit}")
        table.add_row("Days to depletion at mean rate", f"{projection.days_to_cap:,.1f}")
    console.print(table)


def _safe_receipt_rows(
    rows: list[Aggregate], *, kind: str, show_sensitive: bool
) -> list[Aggregate]:
    if show_sensitive:
        return rows
    safe_rows: list[Aggregate] = []
    for index, row in enumerate(rows, start=1):
        if kind == "session":
            timestamp = row.label.split(" | ", 1)[0]
            label = f"Session {index} ({timestamp})"
        elif kind == "project":
            label = f"Project {index}: {short_table_label(row.label) or 'Unknown Project'}"
        else:
            label = row.label
        safe_rows.append(Aggregate(key=f"{kind}-{index}", label=label))
        safe_rows[-1].totals = row.totals
        safe_rows[-1].costs = row.costs
        safe_rows[-1].cache_savings = row.cache_savings
        safe_rows[-1].models = set(row.models)
        safe_rows[-1].service_tiers = set(row.service_tiers)
        safe_rows[-1].plan_types = set(row.plan_types)
        safe_rows[-1].usage_sources = set(row.usage_sources)
        safe_rows[-1].model_context_window = row.model_context_window
        safe_rows[-1].long_context_events = row.long_context_events
        safe_rows[-1].unknown_model_events = row.unknown_model_events
        safe_rows[-1].unknown_tier_events = row.unknown_tier_events
    return safe_rows


@app.command()
def compare(
    a: Annotated[
        str,
        typer.Option(
            "--comparison-window-a",
            "--a",
            help='Window A expression, e.g. "last 7 days".',
        ),
    ] = "last 7 days",
    b: Annotated[
        str,
        typer.Option(
            "--comparison-window-b",
            "--b",
            help='Window B expression, e.g. "previous 7 days".',
        ),
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
    vendors: VendorOpt = None,
    by: Annotated[
        str,
        typer.Option(
            "--comparison-grouping",
            "--by",
            help="total (default) or vendor. Pass vendor to split rows per vendor.",
        ),
    ] = "total",
) -> None:
    """Compare two windows side-by-side. Reports credit and dollar deltas."""
    _validate_format(output_format)
    if by not in {"total", "vendor"}:
        raise _exit_error("--by must be one of: total, vendor")

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
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    result = load_usage(options)
    rate_card = load_rate_card(options)
    agg_a = aggregate_interval(result.events, options, rate_card, interval_a, "A")
    agg_b = aggregate_interval(result.events, options, rate_card, interval_b, "B")

    if by == "vendor":
        _render_compare_by_vendor(
            interval_a=interval_a,
            interval_b=interval_b,
            agg_a=agg_a,
            agg_b=agg_b,
            events=result.events,
            options=options,
            rate_card=rate_card,
            output_format=output_format,
        )
        return

    credits_delta, credits_pct = amount_delta(
        agg_a.costs.adjusted_credits, agg_b.costs.adjusted_credits
    )
    dollars_delta, dollars_pct = amount_delta(agg_a.costs.api_dollars, agg_b.costs.api_dollars)
    tokens_delta, tokens_pct = amount_delta(agg_a.totals.total_tokens, agg_b.totals.total_tokens)
    sparse_warning = sparse_comparison_warning(agg_a, agg_b)

    if output_format == "json":
        typer.echo(
            json_dumps_enveloped(
                {
                    "a": interval_summary(interval_a, agg_a),
                    "b": interval_summary(interval_b, agg_b),
                    "delta": {
                        **amount_fields("credits", credits_delta),
                        "credits_pct": credits_pct,
                        **amount_fields("api_dollars", dollars_delta),
                        "api_dollars_pct": dollars_pct,
                        "tokens": tokens_delta,
                        "tokens_pct": tokens_pct,
                    },
                    "warnings": [sparse_warning] if sparse_warning else [],
                }
            )
        )
        return

    compare_records = [
        {
            "metric": "credits",
            "a": agg_a.costs.adjusted_credits,
            "b": agg_b.costs.adjusted_credits,
            "delta": credits_delta,
            "pct": credits_pct,
        },
        {
            "metric": "api_dollars",
            "a": agg_a.costs.api_dollars,
            "b": agg_b.costs.api_dollars,
            "delta": dollars_delta,
            "pct": dollars_pct,
        },
        {
            "metric": "tokens",
            "a": agg_a.totals.total_tokens,
            "b": agg_b.totals.total_tokens,
            "delta": tokens_delta,
            "pct": tokens_pct,
        },
        {
            "metric": "events",
            "a": agg_a.totals.events,
            "b": agg_b.totals.events,
            "delta": "",
            "pct": "",
        },
    ]
    if output_format == "csv":
        typer.echo(records_to_csv(compare_records), nl=False)
        return
    if output_format == "markdown":
        typer.echo(records_to_markdown(compare_records), nl=False)
        return

    console.print("[bold]Caliper - Compare[/bold]")
    console.print(f"A: {interval_a.label}  ({iso_z(interval_a.start)} → {iso_z(interval_a.end)})")
    console.print(f"B: {interval_b.label}  ({iso_z(interval_b.start)} → {iso_z(interval_b.end)})")
    for warning in pricing_warnings(agg_a) + pricing_warnings(agg_b):
        console.print(f"[yellow]Warning:[/yellow] {warning}")
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
    if sparse_warning:
        console.print(f"[yellow]{sparse_warning}[/yellow]")


def _vendor_compare_rows(
    *,
    events: list,
    options: RuntimeOptions,
    rate_card: RateCard,
    interval_a,
    interval_b,
) -> list[dict]:
    """Build the per-vendor comparison rows for `caliper compare --by vendor`."""
    a_by_vendor = aggregate_interval_by_vendor(events, options, rate_card, interval_a, "A")
    b_by_vendor = aggregate_interval_by_vendor(events, options, rate_card, interval_b, "B")
    vendors = sorted(set(a_by_vendor) | set(b_by_vendor))
    zero = Decimal("0")
    rows: list[dict] = []
    for vendor_id in vendors:
        agg_a = a_by_vendor.get(vendor_id)
        agg_b = b_by_vendor.get(vendor_id)
        credits_a = agg_a.costs.adjusted_credits if agg_a else zero
        credits_b = agg_b.costs.adjusted_credits if agg_b else zero
        dollars_a = agg_a.costs.api_dollars if agg_a else zero
        dollars_b = agg_b.costs.api_dollars if agg_b else zero
        tokens_a = agg_a.totals.total_tokens if agg_a else 0
        tokens_b = agg_b.totals.total_tokens if agg_b else 0
        events_a = agg_a.totals.events if agg_a else 0
        events_b = agg_b.totals.events if agg_b else 0
        credits_delta, credits_pct = amount_delta(credits_a, credits_b)
        dollars_delta, dollars_pct = amount_delta(dollars_a, dollars_b)
        tokens_delta, tokens_pct = amount_delta(tokens_a, tokens_b)
        rows.append(
            {
                "vendor": vendor_id,
                "events_a": events_a,
                "events_b": events_b,
                "credits_a": credits_a,
                "credits_b": credits_b,
                "credits_delta": credits_delta,
                "credits_pct": credits_pct,
                "api_dollars_a": dollars_a,
                "api_dollars_b": dollars_b,
                "api_dollars_delta": dollars_delta,
                "api_dollars_pct": dollars_pct,
                "tokens_a": tokens_a,
                "tokens_b": tokens_b,
                "tokens_delta": tokens_delta,
                "tokens_pct": tokens_pct,
            }
        )
    return rows


def _render_compare_by_vendor(
    *,
    interval_a,
    interval_b,
    agg_a,
    agg_b,
    events: list,
    options: RuntimeOptions,
    rate_card: RateCard,
    output_format: str,
) -> None:
    rows = _vendor_compare_rows(
        events=events,
        options=options,
        rate_card=rate_card,
        interval_a=interval_a,
        interval_b=interval_b,
    )
    sparse_warning = sparse_comparison_warning(agg_a, agg_b)

    if output_format == "json":
        payload: dict[str, Any] = {
            "a": interval_summary(interval_a, agg_a),
            "b": interval_summary(interval_b, agg_b),
            "by_vendor": [
                {
                    "vendor": row["vendor"],
                    "events": {"a": row["events_a"], "b": row["events_b"]},
                    **amount_fields("credits_a", row["credits_a"]),
                    **amount_fields("credits_b", row["credits_b"]),
                    **amount_fields("credits_delta", row["credits_delta"]),
                    "credits_pct": row["credits_pct"],
                    **amount_fields("api_dollars_a", row["api_dollars_a"]),
                    **amount_fields("api_dollars_b", row["api_dollars_b"]),
                    **amount_fields("api_dollars_delta", row["api_dollars_delta"]),
                    "api_dollars_pct": row["api_dollars_pct"],
                    "tokens": {
                        "a": row["tokens_a"],
                        "b": row["tokens_b"],
                        "delta": row["tokens_delta"],
                        "pct": row["tokens_pct"],
                    },
                }
                for row in rows
            ],
            "warnings": [sparse_warning] if sparse_warning else [],
        }
        typer.echo(json_dumps_enveloped(payload))
        return

    if output_format == "csv":
        typer.echo(records_to_csv(rows), nl=False)
        return
    if output_format == "markdown":
        typer.echo(records_to_markdown(rows), nl=False)
        return

    local_console = Console(width=140, _environ={})
    local_console.print("[bold]Caliper - Compare by vendor[/bold]")
    local_console.print(
        f"A: {interval_a.label}  ({iso_z(interval_a.start)} → {iso_z(interval_a.end)})"
    )
    local_console.print(
        f"B: {interval_b.label}  ({iso_z(interval_b.start)} → {iso_z(interval_b.end)})"
    )
    table = Table()
    table.add_column("Vendor")
    table.add_column("Credits A", justify="right")
    table.add_column("Credits B", justify="right")
    table.add_column("Δ Credits", justify="right")
    table.add_column("API $ A", justify="right")
    table.add_column("API $ B", justify="right")
    table.add_column("Δ API $", justify="right")
    table.add_column("Tokens A", justify="right")
    table.add_column("Tokens B", justify="right")
    for row in rows:
        table.add_row(
            row["vendor"],
            f"{row['credits_a']:,.2f}",
            f"{row['credits_b']:,.2f}",
            f"{row['credits_delta']:+,.2f}",
            f"${row['api_dollars_a']:,.2f}",
            f"${row['api_dollars_b']:,.2f}",
            f"{row['api_dollars_delta']:+,.2f}",
            format_int(row["tokens_a"]),
            format_int(row["tokens_b"]),
        )
    local_console.print(table)
    if sparse_warning:
        local_console.print(f"[yellow]{sparse_warning}[/yellow]")


@app.command()
def pr(
    number: Annotated[int | None, typer.Argument(help="Pull request number.")] = None,
    range_spec: Annotated[
        str | None,
        typer.Option("--git-range", "--range", help="Git range, e.g. feature...main."),
    ] = None,
    git_no_network: Annotated[
        bool,
        typer.Option("--local-git-only", "--git-no-network", help="Skip gh-based PR resolution."),
    ] = False,
    output_format: FormatOpt = "table",
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    tier_overrides: TierOverridesOpt = None,
    service_tier: ServiceTierOpt = "auto",
    pricing_mode: PricingModeOpt = "model",
    vendors: VendorOpt = None,
) -> None:
    """Print the cost receipt for a pull request.

    Resolves PR commits via gh by default. Pass --git-range to skip gh."""
    _validate_format(output_format)
    if number is None and range_spec is None:
        raise _exit_error("Provide a PR number or --range A...B.")
    try:
        commits = _resolve_pr_commits(number, range_spec, git_no_network)
        options = build_options(
            days=365.0,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
            tier_overrides=tier_overrides,
            service_tier=service_tier,
            pricing_mode=pricing_mode,
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    _render_commit_scope(
        title=f"PR #{number}" if number is not None else f"Range {range_spec}",
        shas={commit.sha for commit in commits},
        options=options,
        output_format=output_format,
    )


def _resolve_pr_commits(number: int | None, range_spec: str | None, git_no_network: bool):
    if range_spec:
        return commits_for_revspec(range_spec)
    if number is None:
        raise ValueError("Provide a PR number or --range A...B.")
    shas = [] if git_no_network else gh_pr_commit_shas(number)
    if not shas:
        local = local_pull_ref(number)
        if local:
            shas = [local]
    if not shas:
        raise ValueError(
            f"Could not resolve PR #{number}. Run `gh auth login`, fetch refs/pull/{number}/head, "
            "or pass --range A...B."
        )
    return [commit_for_sha(sha) for sha in shas]


@app.command(name="commit")
def commit_command(
    sha: Annotated[str, typer.Argument(help="Commit SHA to attribute.")],
    output_format: FormatOpt = "table",
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    tier_overrides: TierOverridesOpt = None,
    service_tier: ServiceTierOpt = "auto",
    pricing_mode: PricingModeOpt = "model",
    vendors: VendorOpt = None,
) -> None:
    """Print the cost receipt for one commit SHA."""
    _validate_format(output_format)
    try:
        commit = commit_for_sha(sha)
        options = build_options(
            days=365.0,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            rates_file=rates_file,
            tier_overrides=tier_overrides,
            service_tier=service_tier,
            pricing_mode=pricing_mode,
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    _render_commit_scope(
        title=f"Commit {commit.sha[:12]}",
        shas={commit.sha},
        options=options,
        output_format=output_format,
    )


def _render_commit_scope(
    *,
    title: str,
    shas: set[str],
    options: RuntimeOptions,
    output_format: str,
) -> None:
    result = load_usage(options)
    scoped = LoadResult(
        events=[event for event in result.events if event.thread.git_sha in shas],
        duplicates=0,
        tier_sources=result.tier_sources,
        plan_types=result.plan_types,
        credit_samples=[],
        warnings=result.warnings,
    )
    rate_card = load_rate_card(options)
    total = aggregate_total(scoped, options, rate_card=rate_card)
    vendor_rows = _commit_scope_vendor_rows(scoped, options, rate_card)
    payload: dict[str, Any] = {
        "title": title,
        "commits": sorted(shas),
        "totals": {
            "events": total.totals.events,
            "api_dollars": str(total.costs.api_dollars),
            "credits": str(total.costs.adjusted_credits),
            "tokens": total.totals.total_tokens,
            "vendors": sorted(total.vendors),
            "models": sorted(total.models),
        },
        "by_vendor": [
            {
                "vendor": row["vendor"],
                "events": row["events"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cached_input_tokens": row["cached_input_tokens"],
                "cached_pct": row["cached_pct"],
                "api_dollars": str(row["api_dollars"]),
                "credits": str(row["credits"]),
                "models": row["models"],
            }
            for row in vendor_rows
        ],
    }
    if output_format == "json":
        typer.echo(json_dumps_enveloped(payload))
        return
    if output_format == "csv":
        typer.echo(records_to_csv(vendor_rows or [payload["totals"]]), nl=False)
        return
    if output_format == "markdown":
        typer.echo(records_to_markdown(vendor_rows or [payload["totals"]]), nl=False)
        return
    local_console = Console(width=140, _environ={})
    local_console.print(f"[bold]Caliper - {title}[/bold]")
    local_console.print(
        f"{format_int(total.totals.events)} events  "
        f"{format_int(total.totals.total_tokens)} tokens  "
        f"${total.costs.api_dollars:,.2f}  ·  "
        f"{len(shas)} commits"
    )
    if vendor_rows:
        table = Table()
        table.add_column("Vendor")
        table.add_column("Model")
        table.add_column("Events", justify="right")
        table.add_column("Tokens (in/out)", justify="right")
        table.add_column("Cached", justify="right")
        table.add_column("API $", justify="right")
        for row in vendor_rows:
            table.add_row(
                row["vendor"],
                "\n".join(row["models"]) or "-",
                format_int(row["events"]),
                f"{format_int(row['input_tokens'])} / {format_int(row['output_tokens'])}",
                f"{row['cached_pct']:.0f}%",
                f"${row['api_dollars']:,.2f}",
            )
        local_console.print(table)
    else:
        local_console.print("[dim]No matching events recorded for this scope.[/dim]")


def _commit_scope_vendor_rows(
    scoped: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
) -> list[dict]:
    """Break a commit-scope into per-vendor rows for `caliper pr` / `caliper commit`."""
    by_vendor: dict[str, list] = {}
    for event in scoped.events:
        by_vendor.setdefault(event.vendor or "unknown", []).append(event)
    rows: list[dict] = []
    for vendor_id in sorted(by_vendor):
        events = by_vendor[vendor_id]
        result = LoadResult(
            events=events,
            duplicates=0,
            tier_sources={},
            plan_types=set(),
            credit_samples=[],
            warnings=[],
        )
        agg = aggregate_total(result, options, rate_card=rate_card)
        input_tokens = agg.totals.input_tokens
        cached = agg.totals.cached_input_tokens
        cached_pct = (cached / input_tokens * 100) if input_tokens else 0.0
        rows.append(
            {
                "vendor": vendor_id,
                "events": agg.totals.events,
                "input_tokens": agg.totals.input_tokens,
                "output_tokens": agg.totals.output_tokens,
                "cached_input_tokens": cached,
                "cached_pct": cached_pct,
                "api_dollars": agg.costs.api_dollars,
                "credits": agg.costs.adjusted_credits,
                "models": sorted(agg.models),
            }
        )
    return rows


def _validate_whatif_inputs(tier: str | None, model: str | None, output_format: str) -> None:
    if tier is None and model is None:
        raise _exit_error(
            "Provide --hypothetical-service-tier and/or --hypothetical-model "
            "to evaluate a hypothetical."
        )
    if tier is not None and tier not in {"standard", "fast"}:
        raise _exit_error("--hypothetical-service-tier must be one of: standard, fast")
    if model is not None and model not in available_model_names():
        raise _exit_error(
            f"--hypothetical-model {model!r} is not in the active rate card/catalog. "
            f"Use one of: {', '.join(sorted(available_model_names()))}"
        )
    _validate_format(output_format)


def _render_whatif_report(report, output_format: str) -> None:
    if output_format == "json":
        typer.echo(json_dumps_enveloped(report.json_payload()))
        return
    if output_format == "csv":
        typer.echo(records_to_csv(report.records()), nl=False)
        return
    if output_format == "markdown":
        typer.echo(records_to_markdown(report.records()), nl=False)
        return
    if report.noop:
        console.print(report.noop_message)
        return
    _render_whatif_table(report)


def _render_whatif_table(report) -> None:
    totals = report.totals
    if totals is None:
        raise _exit_error("what-if totals are unavailable")
    console.print(f"[bold]Caliper - What If ({report.label})[/bold]")
    console.print(f"Trailing {report.days} days · {report.events_evaluated:,} events")
    for warning in report.pricing_warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    table = Table()
    table.add_column("Metric")
    table.add_column("Actual", justify="right")
    table.add_column("Projected", justify="right")
    table.add_column("Δ", justify="right")
    table.add_column("%", justify="right")
    table.add_row(
        "Credits",
        f"{totals.actual_credits:,.2f}",
        f"{totals.hypothetical_credits:,.2f}",
        f"{totals.credit_delta:+,.2f}",
        f"{totals.credit_pct:+.1f}%",
    )
    table.add_row(
        "API $",
        f"${totals.actual_dollars:,.2f}",
        f"${totals.hypothetical_dollars:,.2f}",
        f"{totals.dollar_delta:+,.2f}",
        f"{totals.dollar_pct:+.1f}%",
    )
    console.print(table)


@app.command()
def whatif(
    days: Annotated[
        int,
        typer.Option(
            "--scenario-history-days",
            "--days",
            min=1,
            max=365,
            help="Trailing day window.",
        ),
    ] = 7,
    tier: Annotated[
        str | None,
        typer.Option(
            "--hypothetical-service-tier",
            "--tier",
            help="Hypothetical tier: standard or fast.",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--hypothetical-model",
            "--model",
            help="Hypothetical model name (must be in rate card).",
        ),
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
    vendors: VendorOpt = None,
) -> None:
    """Re-price the window as if you had used a different tier or model."""
    _validate_whatif_inputs(tier, model, output_format)

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
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    result = load_usage(options)
    rate_card = load_rate_card(options)
    report = build_whatif_report(
        result,
        options,
        rate_card,
        days=days,
        tier=tier,
        model=model,
    )
    _render_whatif_report(report, output_format)


@app.command()
def advise(
    strict: Annotated[
        bool,
        typer.Option(
            "--strict-confidence",
            "--strict",
            help="Only show suggestions with confidence >= 0.8.",
        ),
    ] = False,
    explain: Annotated[
        str | None,
        typer.Option("--explain-rule", "--explain", help="Explain one rule id and exit."),
    ] = None,
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = 7.0,
    timezone: TimezoneOpt = "local",
    output_format: FormatOpt = "table",
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
    vendors: VendorOpt = None,
) -> None:
    """Suggest model or tier swaps that would have cut cost on past usage."""
    _validate_format(output_format)
    if explain:
        try:
            payload = explain_arbitrage(explain)
        except ValueError as exc:
            raise _exit_error(str(exc)) from exc
        _emit_records([payload], output_format, "Caliper - Advisor Rule")
        return
    try:
        options = build_options(
            since=since,
            until=until,
            days=days,
            timezone=timezone,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            pricing_mode=pricing_mode,
            service_tier=service_tier,
            unknown_service_tier=unknown_service_tier,
            tier_overrides=tier_overrides,
            rates_file=rates_file,
            no_dedupe=no_dedupe,
            no_parse_cache=no_parse_cache,
            default_model=default_model,
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    result = load_usage(options)
    rows = [item.to_record() for item in suggest_arbitrage(result.events, 0.8 if strict else 0.6)]
    _emit_records(rows, output_format, "Caliper - Advisor")


def _emit_records(records: list[dict], output_format: str, title: str) -> None:
    if output_format == "json":
        typer.echo(json_dumps_enveloped({"records": records}))
        return
    if output_format == "csv":
        typer.echo(records_to_csv(records), nl=False)
        return
    if output_format == "markdown":
        typer.echo(records_to_markdown(records), nl=False)
        return
    console.print(f"[bold]{title}[/bold]")
    if not records:
        console.print("No suggestions for this window.")
        return
    table = Table(show_lines=False)
    for key in records[0]:
        table.add_column(key)
    for record in records:
        table.add_row(*(str(record.get(key, "")) for key in records[0]))
    console.print(table)


export_app = typer.Typer(help="Render receipts, Grafana dashboards, and Prometheus metrics.")
app.add_typer(export_app, name="export")


@export_app.command("prometheus")
def export_prometheus(
    host: Annotated[
        str,
        typer.Option(
            "--metrics-bind-host",
            "--host",
            help="Bind address. Default 127.0.0.1 to keep metrics local.",
        ),
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--metrics-port", "--port", help="TCP port.")] = 9090,
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
    config: ConfigOpt = None,
    rates_file: RatesFileOpt = None,
    tier_overrides: TierOverridesOpt = None,
    service_tier: ServiceTierOpt = "auto",
    pricing_mode: PricingModeOpt = "model",
    vendors: VendorOpt = None,
) -> None:
    """Serve /metrics for Prometheus. Defaults to 127.0.0.1. Pass --host 0.0.0.0 to expose."""
    try:
        from caliper.prom_export import serve_forever
    except ImportError as exc:
        raise _exit_error(
            "prometheus-client is not installed. Install with: pip install 'caliper-ai[prom]'"
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
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    console.print(f"[green]Prometheus exporter listening on http://{host}:{port}/metrics[/green]")
    try:
        serve_forever(host, port, lambda: build_prometheus_snapshot(options))
    except OSError as exc:
        raise _exit_error(
            f"could not bind {host}:{port}: {exc}. "
            f"Try a different --port or check that no other exporter is running."
        ) from exc


@export_app.command("grafana")
def export_grafana(
    title: Annotated[
        str,
        typer.Option("--dashboard-title", "--title", help="Dashboard title."),
    ] = "Caliper",
    output: OutputOpt = None,
) -> None:
    """Print a Grafana dashboard JSON wired to the Prometheus exporter metric names."""
    text = render_grafana_dashboard(title=title)
    if output:
        output.expanduser().write_text(text)
    else:
        typer.echo(text)


@export_app.command("receipt")
def export_receipt(
    month: Annotated[str, typer.Option("--receipt-month", "--month", help="Month YYYY-MM.")] = "",
    receipt_format: Annotated[
        str,
        typer.Option("--receipt-format", "--format", "-f", help="markdown or html."),
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
    vendors: VendorOpt = None,
    top: Annotated[
        int,
        typer.Option(
            "--receipt-row-limit",
            "--top",
            min=1,
            max=50,
            help="Rows in 'top sessions' / 'top projects'.",
        ),
    ] = 5,
    show_sensitive: Annotated[
        bool,
        typer.Option(
            "--include-sensitive-receipt-data",
            "--show-sensitive",
            help="Include full session labels and local project paths in the receipt.",
        ),
    ] = False,
) -> None:
    """Render a monthly cost receipt as Markdown or HTML. Suitable for finance handoff."""
    if receipt_format not in {"markdown", "html"}:
        raise _exit_error("--receipt-format must be one of: markdown, html")

    now = dt.datetime.now(tz=local_timezone())
    chosen_month = month or now.strftime("%Y-%m")
    try:
        start, end = month_bounds(chosen_month, local_timezone())
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    span_days = (end - start).total_seconds() / 86400.0
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
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    result = load_usage(options)
    rate_card = load_rate_card(options)

    in_month = [event for event in result.events if start <= event.timestamp < end]
    scoped = LoadResult(
        events=in_month,
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
    )

    from caliper.aggregation import (
        aggregate_model_mode,
        aggregate_projects,
        aggregate_sessions,
        aggregate_total,
    )

    totals = aggregate_total(scoped, options, label="Month", rate_card=rate_card)
    by_model = aggregate_model_mode(scoped, options, rate_card=rate_card)
    top_sessions = _safe_receipt_rows(
        aggregate_sessions(scoped, options, rate_card=rate_card)[:top],
        kind="session",
        show_sensitive=show_sensitive,
    )
    top_projects = _safe_receipt_rows(
        aggregate_projects(scoped, options, rate_card=rate_card)[:top],
        kind="project",
        show_sensitive=show_sensitive,
    )

    payload = ReceiptInputs(
        month=chosen_month,
        totals=totals,
        by_model=by_model,
        top_sessions=top_sessions,
        top_projects=top_projects,
        generated_at=now,
        tier_sources=result.tier_sources,
        insights=[item.title for item in build_insights(scoped, options, rate_card=rate_card)[:3]],
        warning_count=len(result.warnings),
        pricing_status=pricing_status(totals),
        pricing_warnings=pricing_warnings(totals),
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


budgets_app = typer.Typer(help="Check usage against budgets and gate CI on cost.")
app.add_typer(budgets_app, name="budgets")


def _severity_style(severity: str) -> str:
    if severity == SEVERITY_BREACH:
        return "[red]breach[/red]"
    if severity == SEVERITY_WARN:
        return "[yellow]warn[/yellow]"
    return "[green]ok[/green]"


def _render_budget_report(
    *,
    output_format: str,
    records: list[dict],
    alerts,
    worst: str,
    pricing_status_value: str,
    warnings: list[str],
) -> None:
    if output_format == "json":
        typer.echo(
            json_dumps_enveloped(
                {
                    "alerts": records,
                    "max_severity": worst,
                    "pricing_status": pricing_status_value,
                    "pricing_warnings": warnings,
                }
            )
        )
        raise typer.Exit(SEVERITY_EXIT_CODE[worst])

    if output_format == "csv":
        typer.echo(records_to_csv(records), nl=False)
        raise typer.Exit(SEVERITY_EXIT_CODE[worst])

    if output_format == "markdown":
        typer.echo(records_to_markdown(records), nl=False)
        raise typer.Exit(SEVERITY_EXIT_CODE[worst])

    _render_budget_table(alerts, worst, warnings)
    raise typer.Exit(SEVERITY_EXIT_CODE[worst])


def _render_budget_table(alerts, worst: str, warnings: list[str]) -> None:
    console.print("[bold]Caliper - Budgets[/bold]")
    for warning in warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
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
    vendors: VendorOpt = None,
    output_format: FormatOpt = "table",
) -> None:
    """Check the \\[budgets] table in .caliper.toml. Exits 0 ok, 1 warn, 2 breach.

    Wire into CI: a non-zero exit fails the job."""
    _validate_format(output_format)
    try:
        loaded = load_config(config) if config else load_config()
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    raw = loaded.get("budgets") or {}
    try:
        budget_list = parse_budgets_table(raw if isinstance(raw, dict) else {})
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    if not budget_list:
        console.print(
            "No budgets defined. Add a [budgets] table to .caliper.toml. "
            "Example: daily_credits = 25000.",
            markup=False,
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
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc

    result = load_usage(options)
    rate_card = load_rate_card(options)
    total = aggregate_total(result, options, rate_card=rate_card)
    status = pricing_status(total)
    warnings = pricing_warnings(total)
    now = dt.datetime.now(tz=local_timezone())
    usage = usage_for_periods(result.events, options, rate_card, now)
    alerts = evaluate_budgets(budget_list, usage)
    worst = max_severity(alerts)
    records = alert_records(alerts, usage, status)
    _render_budget_report(
        output_format=output_format,
        records=records,
        alerts=alerts,
        worst=worst,
        pricing_status_value=status,
        warnings=warnings,
    )


@app.command()
def statusline(
    since: SinceOpt = None,
    until: UntilOpt = None,
    days: DaysOpt = 7.0,
    timezone: TimezoneOpt = "local",
    output_format: StatuslineFormatOpt = "text",
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
    offline: OfflineOpt = True,
    vendors: VendorOpt = None,
    watch: Annotated[
        float | None,
        typer.Option(
            "--watch-interval",
            "--watch",
            min=0.1,
            help="Print one snapshot every N seconds.",
        ),
    ] = None,
    max_ticks: Annotated[
        int | None,
        typer.Option("--watch-max-ticks", "--max-ticks", help="Stop watch mode after N snapshots."),
    ] = None,
) -> None:
    """Print a one-line cost snapshot. Good for shell prompts and CI hooks."""
    if output_format not in {"text", "json"}:
        raise _exit_error("--output-format must be one of: text, json")
    ticks = 0
    while True:
        text = _statusline_text(
            since=since,
            until=until,
            days=days,
            timezone=timezone,
            output_format=output_format,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            pricing_mode=pricing_mode,
            service_tier=service_tier,
            unknown_service_tier=unknown_service_tier,
            tier_overrides=tier_overrides,
            rates_file=rates_file,
            no_dedupe=no_dedupe,
            no_parse_cache=no_parse_cache,
            default_model=default_model,
            offline=offline,
            vendors=vendors,
        )
        if output:
            output.expanduser().write_text(text)
        else:
            typer.echo(text, nl=False)
        ticks += 1
        if watch is None or (max_ticks is not None and ticks >= max_ticks):
            return
        time.sleep(watch)


def _statusline_text(
    *,
    since: str | None,
    until: str | None,
    days: float | None,
    timezone: str,
    output_format: str,
    session_root: Path | None,
    state_db: Path | None,
    codex_config: Path | None,
    config: Path | None,
    pricing_mode: str,
    service_tier: str,
    unknown_service_tier: str,
    tier_overrides: Path | None,
    rates_file: Path | None,
    no_dedupe: bool,
    no_parse_cache: bool,
    default_model: str,
    offline: bool,
    vendors: list[str] | None,
) -> str:
    try:
        options = build_options(
            since=since,
            until=until or iso_z(dt.datetime.now(tz=local_timezone())),
            days=days,
            timezone=timezone,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
            config=config,
            pricing_mode=pricing_mode,
            service_tier=service_tier,
            unknown_service_tier=unknown_service_tier,
            tier_overrides=tier_overrides,
            rates_file=rates_file,
            no_dedupe=no_dedupe,
            no_parse_cache=no_parse_cache,
            default_model=default_model,
            offline=offline,
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    result = load_usage(options)
    rate_card = load_rate_card(options)
    snapshot = build_statusline_snapshot(result, options, rate_card, now=options.end)
    if output_format == "json":
        return (
            json.dumps(
                with_caliper_envelope(statusline_payload(snapshot)),
                separators=(",", ":"),
            )
            + "\n"
        )
    return render_statusline_text(snapshot) + "\n"


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
    no_parse_cache: NoParseCacheOpt = False,
    vendors: VendorOpt = None,
    interval: Annotated[
        float,
        typer.Option(
            "--refresh-interval",
            "--interval",
            "-i",
            min=0.5,
            help="Refresh seconds. Default 2.",
        ),
    ] = 2.0,
    max_ticks: Annotated[
        int | None,
        typer.Option("--refresh-max-ticks", "--max-ticks", help="Stop after N ticks."),
    ] = None,
) -> None:
    """Open a live TUI. Today's usage, 5-hour and weekly window countdowns, burn rate."""
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
            no_parse_cache=no_parse_cache,
            vendors=vendors,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
    run_live(options, interval=interval, max_ticks=max_ticks)
