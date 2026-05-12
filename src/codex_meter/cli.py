from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

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
from codex_meter.config import build_options
from codex_meter.models import LoadResult
from codex_meter.parser import load_usage
from codex_meter.render import format_int, render
from codex_meter.timeutil import iso_z, local_timezone

app = typer.Typer(
    help="Offline-first Codex usage reports for tokens, credits, costs, sessions, and projects.",
    no_args_is_help=False,
)
console = Console()


FormatOpt = Annotated[str, typer.Option("--format", "-f", help="table, json, csv, or markdown.")]
PathOpt = Annotated[Path | None, typer.Option()]


def version_callback(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-v", callback=version_callback, help="Show version and exit."),
    ] = False,
) -> None:
    if ctx.invoked_subcommand is None:
        run_overview()


def make_options(
    since: str | None,
    until: str | None,
    days: float | None,
    timezone: str,
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
    default_model: str,
    show_prompts: bool,
    offline: bool,
    compact: bool,
    top_threads: int,
):
    try:
        return build_options(
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
            default_model=default_model,
            show_prompts=show_prompts,
            offline=offline,
            compact=compact,
            top_threads=top_threads,
        )
    except ValueError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(2) from exc


def command_options(
    since: str | None = None,
    until: str | None = None,
    days: float | None = None,
    timezone: str = "local",
    session_root: Path | None = None,
    state_db: Path | None = None,
    codex_config: Path | None = None,
    config: Path | None = None,
    pricing_mode: str = "model",
    service_tier: str = "auto",
    unknown_service_tier: str = "current-config",
    tier_overrides: Path | None = None,
    rates_file: Path | None = None,
    no_dedupe: bool = False,
    default_model: str = "gpt-5.5",
    show_prompts: bool = False,
    offline: bool = True,
    compact: bool = False,
    top_threads: int = 10,
):
    return make_options(
        since,
        until,
        days,
        timezone,
        session_root,
        state_db,
        codex_config,
        config,
        pricing_mode,
        service_tier,
        unknown_service_tier,
        tier_overrides,
        rates_file,
        no_dedupe,
        default_model,
        show_prompts,
        offline,
        compact,
        top_threads,
    )


def usage_kwargs(values: dict) -> dict:
    ignored = {"output_format", "output"}
    return {key: value for key, value in values.items() if key not in ignored}


def run_overview(output_format: str = "table", output: Path | None = None) -> None:
    now = dt.datetime.now(tz=local_timezone())
    longest_options = build_options(days=90, until=iso_z(now))
    longest_result = load_usage(longest_options)
    rows = []
    for days in (7, 30, 90):
        start = now - dt.timedelta(days=days)
        period_events = [event for event in longest_result.events if start <= event.timestamp < now]
        period_result = LoadResult(
            events=period_events,
            duplicates=0,
            tier_sources=longest_result.tier_sources,
            plan_types=longest_result.plan_types,
            credit_samples=[],
            warnings=longest_result.warnings,
        )
        total = aggregate_total(period_result, longest_options, label=f"Last {days} days")
        rows.append(total)
    render(longest_result, longest_options, rows, "overview", output_format, output)


def run_grouped(command: str, rows_fn, output_format: str, output: Path | None, **kwargs) -> None:
    options = command_options(**kwargs)
    result = load_usage(options)
    rows = rows_fn(result, options)
    render(result, options, rows, command, output_format, output)


COMMON_HELP = {
    "since": "Start date/time. Supports YYYY-MM-DD, YYYYMMDD, or ISO datetimes.",
    "until": "End date/time. Defaults to now.",
    "days": "Rolling day window before --until.",
    "timezone": "Timezone for grouping. Use local or an IANA name.",
    "session_root": "Codex session JSONL root.",
    "state_db": "Codex state_5.sqlite path.",
    "codex_config": "Codex config.toml path.",
    "config": "codex-meter config TOML path.",
    "output": "Write output to a file.",
}


def common_command_params(**kwargs):
    return kwargs


@app.command()
def overview(
    output_format: FormatOpt = "table",
    output: PathOpt = None,
) -> None:
    """Show rolling 7/30/90 day usage."""
    run_overview(output_format, output)


@app.command()
def daily(
    since: Annotated[str | None, typer.Option("--since", "-s", help=COMMON_HELP["since"])] = None,
    until: Annotated[str | None, typer.Option("--until", "-u", help=COMMON_HELP["until"])] = None,
    days: Annotated[float | None, typer.Option("--days", help=COMMON_HELP["days"])] = None,
    timezone: Annotated[
        str, typer.Option("--timezone", "-z", help=COMMON_HELP["timezone"])
    ] = "local",
    output_format: FormatOpt = "table",
    output: PathOpt = None,
    session_root: Annotated[
        Path | None, typer.Option("--session-root", help=COMMON_HELP["session_root"])
    ] = None,
    state_db: Annotated[
        Path | None, typer.Option("--state-db", help=COMMON_HELP["state_db"])
    ] = None,
    codex_config: Annotated[
        Path | None, typer.Option("--codex-config", help=COMMON_HELP["codex_config"])
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help=COMMON_HELP["config"])] = None,
    pricing_mode: Annotated[str, typer.Option("--pricing-mode")] = "model",
    service_tier: Annotated[str, typer.Option("--service-tier")] = "auto",
    unknown_service_tier: Annotated[str, typer.Option("--unknown-service-tier")] = "current-config",
    tier_overrides: Annotated[Path | None, typer.Option("--tier-overrides")] = None,
    rates_file: Annotated[Path | None, typer.Option("--rates-file")] = None,
    no_dedupe: Annotated[bool, typer.Option("--no-dedupe")] = False,
    default_model: Annotated[str, typer.Option("--default-model")] = "gpt-5.5",
    show_prompts: Annotated[bool, typer.Option("--show-prompts")] = False,
    offline: Annotated[bool, typer.Option("--offline/--no-offline")] = True,
    compact: Annotated[bool, typer.Option("--compact")] = False,
    top_threads: Annotated[int, typer.Option("--top-threads")] = 10,
) -> None:
    """Show usage grouped by day."""
    run_grouped("daily", aggregate_daily, output_format, output, **usage_kwargs(locals()))


@app.command()
def weekly(
    since: Annotated[str | None, typer.Option("--since", "-s", help=COMMON_HELP["since"])] = None,
    until: Annotated[str | None, typer.Option("--until", "-u", help=COMMON_HELP["until"])] = None,
    days: Annotated[float | None, typer.Option("--days", help=COMMON_HELP["days"])] = None,
    timezone: Annotated[
        str, typer.Option("--timezone", "-z", help=COMMON_HELP["timezone"])
    ] = "local",
    output_format: FormatOpt = "table",
    output: PathOpt = None,
    session_root: Annotated[
        Path | None, typer.Option("--session-root", help=COMMON_HELP["session_root"])
    ] = None,
    state_db: Annotated[
        Path | None, typer.Option("--state-db", help=COMMON_HELP["state_db"])
    ] = None,
    codex_config: Annotated[
        Path | None, typer.Option("--codex-config", help=COMMON_HELP["codex_config"])
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help=COMMON_HELP["config"])] = None,
    pricing_mode: Annotated[str, typer.Option("--pricing-mode")] = "model",
    service_tier: Annotated[str, typer.Option("--service-tier")] = "auto",
    unknown_service_tier: Annotated[str, typer.Option("--unknown-service-tier")] = "current-config",
    tier_overrides: Annotated[Path | None, typer.Option("--tier-overrides")] = None,
    rates_file: Annotated[Path | None, typer.Option("--rates-file")] = None,
    no_dedupe: Annotated[bool, typer.Option("--no-dedupe")] = False,
    default_model: Annotated[str, typer.Option("--default-model")] = "gpt-5.5",
    show_prompts: Annotated[bool, typer.Option("--show-prompts")] = False,
    offline: Annotated[bool, typer.Option("--offline/--no-offline")] = True,
    compact: Annotated[bool, typer.Option("--compact")] = False,
    top_threads: Annotated[int, typer.Option("--top-threads")] = 10,
) -> None:
    """Show usage grouped by ISO week."""
    run_grouped("weekly", aggregate_weekly, output_format, output, **usage_kwargs(locals()))


@app.command()
def monthly(
    since: Annotated[str | None, typer.Option("--since", "-s", help=COMMON_HELP["since"])] = None,
    until: Annotated[str | None, typer.Option("--until", "-u", help=COMMON_HELP["until"])] = None,
    days: Annotated[float | None, typer.Option("--days", help=COMMON_HELP["days"])] = None,
    timezone: Annotated[
        str, typer.Option("--timezone", "-z", help=COMMON_HELP["timezone"])
    ] = "local",
    output_format: FormatOpt = "table",
    output: PathOpt = None,
    session_root: Annotated[
        Path | None, typer.Option("--session-root", help=COMMON_HELP["session_root"])
    ] = None,
    state_db: Annotated[
        Path | None, typer.Option("--state-db", help=COMMON_HELP["state_db"])
    ] = None,
    codex_config: Annotated[
        Path | None, typer.Option("--codex-config", help=COMMON_HELP["codex_config"])
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help=COMMON_HELP["config"])] = None,
    pricing_mode: Annotated[str, typer.Option("--pricing-mode")] = "model",
    service_tier: Annotated[str, typer.Option("--service-tier")] = "auto",
    unknown_service_tier: Annotated[str, typer.Option("--unknown-service-tier")] = "current-config",
    tier_overrides: Annotated[Path | None, typer.Option("--tier-overrides")] = None,
    rates_file: Annotated[Path | None, typer.Option("--rates-file")] = None,
    no_dedupe: Annotated[bool, typer.Option("--no-dedupe")] = False,
    default_model: Annotated[str, typer.Option("--default-model")] = "gpt-5.5",
    show_prompts: Annotated[bool, typer.Option("--show-prompts")] = False,
    offline: Annotated[bool, typer.Option("--offline/--no-offline")] = True,
    compact: Annotated[bool, typer.Option("--compact")] = False,
    top_threads: Annotated[int, typer.Option("--top-threads")] = 10,
) -> None:
    """Show usage grouped by month."""
    run_grouped("monthly", aggregate_monthly, output_format, output, **usage_kwargs(locals()))


@app.command(name="session")
def session_command(
    since: Annotated[str | None, typer.Option("--since", "-s", help=COMMON_HELP["since"])] = None,
    until: Annotated[str | None, typer.Option("--until", "-u", help=COMMON_HELP["until"])] = None,
    days: Annotated[float | None, typer.Option("--days", help=COMMON_HELP["days"])] = None,
    timezone: Annotated[
        str, typer.Option("--timezone", "-z", help=COMMON_HELP["timezone"])
    ] = "local",
    output_format: FormatOpt = "table",
    output: PathOpt = None,
    session_root: Annotated[
        Path | None, typer.Option("--session-root", help=COMMON_HELP["session_root"])
    ] = None,
    state_db: Annotated[
        Path | None, typer.Option("--state-db", help=COMMON_HELP["state_db"])
    ] = None,
    codex_config: Annotated[
        Path | None, typer.Option("--codex-config", help=COMMON_HELP["codex_config"])
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help=COMMON_HELP["config"])] = None,
    pricing_mode: Annotated[str, typer.Option("--pricing-mode")] = "model",
    service_tier: Annotated[str, typer.Option("--service-tier")] = "auto",
    unknown_service_tier: Annotated[str, typer.Option("--unknown-service-tier")] = "current-config",
    tier_overrides: Annotated[Path | None, typer.Option("--tier-overrides")] = None,
    rates_file: Annotated[Path | None, typer.Option("--rates-file")] = None,
    no_dedupe: Annotated[bool, typer.Option("--no-dedupe")] = False,
    default_model: Annotated[str, typer.Option("--default-model")] = "gpt-5.5",
    show_prompts: Annotated[bool, typer.Option("--show-prompts")] = False,
    offline: Annotated[bool, typer.Option("--offline/--no-offline")] = True,
    compact: Annotated[bool, typer.Option("--compact")] = False,
    top_threads: Annotated[int, typer.Option("--top-threads")] = 10,
) -> None:
    """Show usage grouped by Codex session."""
    run_grouped("session", aggregate_sessions, output_format, output, **usage_kwargs(locals()))


@app.command()
def project(
    since: Annotated[str | None, typer.Option("--since", "-s", help=COMMON_HELP["since"])] = None,
    until: Annotated[str | None, typer.Option("--until", "-u", help=COMMON_HELP["until"])] = None,
    days: Annotated[float | None, typer.Option("--days", help=COMMON_HELP["days"])] = None,
    timezone: Annotated[
        str, typer.Option("--timezone", "-z", help=COMMON_HELP["timezone"])
    ] = "local",
    output_format: FormatOpt = "table",
    output: PathOpt = None,
    session_root: Annotated[
        Path | None, typer.Option("--session-root", help=COMMON_HELP["session_root"])
    ] = None,
    state_db: Annotated[
        Path | None, typer.Option("--state-db", help=COMMON_HELP["state_db"])
    ] = None,
    codex_config: Annotated[
        Path | None, typer.Option("--codex-config", help=COMMON_HELP["codex_config"])
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help=COMMON_HELP["config"])] = None,
    pricing_mode: Annotated[str, typer.Option("--pricing-mode")] = "model",
    service_tier: Annotated[str, typer.Option("--service-tier")] = "auto",
    unknown_service_tier: Annotated[str, typer.Option("--unknown-service-tier")] = "current-config",
    tier_overrides: Annotated[Path | None, typer.Option("--tier-overrides")] = None,
    rates_file: Annotated[Path | None, typer.Option("--rates-file")] = None,
    no_dedupe: Annotated[bool, typer.Option("--no-dedupe")] = False,
    default_model: Annotated[str, typer.Option("--default-model")] = "gpt-5.5",
    show_prompts: Annotated[bool, typer.Option("--show-prompts")] = False,
    offline: Annotated[bool, typer.Option("--offline/--no-offline")] = True,
    compact: Annotated[bool, typer.Option("--compact")] = False,
    top_threads: Annotated[int, typer.Option("--top-threads")] = 10,
) -> None:
    """Show usage grouped by project/cwd."""
    run_grouped("project", aggregate_projects, output_format, output, **usage_kwargs(locals()))


@app.command()
def limits(
    since: Annotated[str | None, typer.Option("--since", "-s", help=COMMON_HELP["since"])] = None,
    until: Annotated[str | None, typer.Option("--until", "-u", help=COMMON_HELP["until"])] = None,
    days: Annotated[float | None, typer.Option("--days", help=COMMON_HELP["days"])] = 7,
    timezone: Annotated[
        str, typer.Option("--timezone", "-z", help=COMMON_HELP["timezone"])
    ] = "local",
    session_root: Annotated[
        Path | None, typer.Option("--session-root", help=COMMON_HELP["session_root"])
    ] = None,
    state_db: Annotated[
        Path | None, typer.Option("--state-db", help=COMMON_HELP["state_db"])
    ] = None,
    codex_config: Annotated[
        Path | None, typer.Option("--codex-config", help=COMMON_HELP["codex_config"])
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help=COMMON_HELP["config"])] = None,
    pricing_mode: Annotated[str, typer.Option("--pricing-mode")] = "model",
    service_tier: Annotated[str, typer.Option("--service-tier")] = "auto",
    unknown_service_tier: Annotated[str, typer.Option("--unknown-service-tier")] = "current-config",
    tier_overrides: Annotated[Path | None, typer.Option("--tier-overrides")] = None,
    rates_file: Annotated[Path | None, typer.Option("--rates-file")] = None,
    no_dedupe: Annotated[bool, typer.Option("--no-dedupe")] = False,
    default_model: Annotated[str, typer.Option("--default-model")] = "gpt-5.5",
    show_prompts: Annotated[bool, typer.Option("--show-prompts")] = False,
    offline: Annotated[bool, typer.Option("--offline/--no-offline")] = True,
    compact: Annotated[bool, typer.Option("--compact")] = False,
    top_threads: Annotated[int, typer.Option("--top-threads")] = 10,
) -> None:
    """Show recent rate-limit and credit samples."""
    options = command_options(**locals())
    result = load_usage(options)
    console.print("[bold]Codex Meter - Limits[/bold]")
    if not result.credit_samples:
        console.print("No rate-limit samples with credits fields found.")
        return
    for event in result.credit_samples:
        console.print(
            f"- {iso_z(event.timestamp)} | credits={event.credits} | "
            f"primary={event.primary_used_percent}% | secondary={event.secondary_used_percent}%"
        )


@app.command()
def doctor(
    session_root: Annotated[
        Path | None, typer.Option("--session-root", help=COMMON_HELP["session_root"])
    ] = None,
    state_db: Annotated[
        Path | None, typer.Option("--state-db", help=COMMON_HELP["state_db"])
    ] = None,
    codex_config: Annotated[
        Path | None, typer.Option("--codex-config", help=COMMON_HELP["codex_config"])
    ] = None,
) -> None:
    """Check local Codex data paths."""
    options = build_options(
        days=1,
        session_root=session_root,
        state_db=state_db,
        codex_config=codex_config,
    )
    files = list(options.session_root.glob("**/*.jsonl")) if options.session_root.exists() else []
    session_status = "OK" if options.session_root.exists() else "MISSING"
    state_status = "OK" if options.state_db.exists() else "MISSING"
    config_status = "OK" if options.config_path.exists() else "MISSING"
    console.print("[bold]Codex Meter - Doctor[/bold]")
    console.print(f"Session root: {options.session_root} {session_status}")
    console.print(f"Session files: {format_int(len(files))}")
    console.print(f"State DB: {options.state_db} {state_status}")
    console.print(f"Codex config: {options.config_path} {config_status}")
    console.print("Pricing: embedded offline rate card")


@app.command()
def models(
    since: Annotated[str | None, typer.Option("--since", "-s", help=COMMON_HELP["since"])] = None,
    until: Annotated[str | None, typer.Option("--until", "-u", help=COMMON_HELP["until"])] = None,
    days: Annotated[float | None, typer.Option("--days", help=COMMON_HELP["days"])] = None,
    timezone: Annotated[
        str, typer.Option("--timezone", "-z", help=COMMON_HELP["timezone"])
    ] = "local",
    output_format: FormatOpt = "table",
    output: PathOpt = None,
    session_root: Annotated[
        Path | None, typer.Option("--session-root", help=COMMON_HELP["session_root"])
    ] = None,
    state_db: Annotated[
        Path | None, typer.Option("--state-db", help=COMMON_HELP["state_db"])
    ] = None,
    codex_config: Annotated[
        Path | None, typer.Option("--codex-config", help=COMMON_HELP["codex_config"])
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help=COMMON_HELP["config"])] = None,
    pricing_mode: Annotated[str, typer.Option("--pricing-mode")] = "model",
    service_tier: Annotated[str, typer.Option("--service-tier")] = "auto",
    unknown_service_tier: Annotated[str, typer.Option("--unknown-service-tier")] = "current-config",
    tier_overrides: Annotated[Path | None, typer.Option("--tier-overrides")] = None,
    rates_file: Annotated[Path | None, typer.Option("--rates-file")] = None,
    no_dedupe: Annotated[bool, typer.Option("--no-dedupe")] = False,
    default_model: Annotated[str, typer.Option("--default-model")] = "gpt-5.5",
    show_prompts: Annotated[bool, typer.Option("--show-prompts")] = False,
    offline: Annotated[bool, typer.Option("--offline/--no-offline")] = True,
    compact: Annotated[bool, typer.Option("--compact")] = False,
    top_threads: Annotated[int, typer.Option("--top-threads")] = 10,
) -> None:
    """Show usage grouped by model and service tier."""
    run_grouped("models", aggregate_model_mode, output_format, output, **usage_kwargs(locals()))
