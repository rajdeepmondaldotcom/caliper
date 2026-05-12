from __future__ import annotations

import datetime as dt
from collections.abc import Callable
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
from codex_meter.models import Aggregate, LoadResult, RuntimeOptions
from codex_meter.parser import load_usage
from codex_meter.pricing import MODEL_CARDS, PRICING_SOURCES, RateCard
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
DefaultModelOpt = Annotated[str, typer.Option("--default-model")]
ShowPromptsOpt = Annotated[bool, typer.Option("--show-prompts")]
OfflineOpt = Annotated[bool, typer.Option("--offline/--no-offline")]
CompactOpt = Annotated[bool, typer.Option("--compact")]
TopThreadsOpt = Annotated[int, typer.Option("--top-threads")]
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
    "default_model",
    "show_prompts",
    "offline",
    "compact",
    "top_threads",
)


def _exit_error(message: str) -> typer.Exit:
    console.print(f"[red]error:[/red] {message}")
    return typer.Exit(2)


def _validate_format(output_format: str) -> None:
    if output_format not in OUTPUT_FORMATS:
        raise _exit_error(f"--format must be one of: {', '.join(OUTPUT_FORMATS)}")


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
    rows = rows_fn(result, options)
    render(result, options, rows, name, values["output_format"], values["output"])


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
        _run_overview("table", None)


def _run_overview(output_format: str, output: Path | None) -> None:
    _validate_format(output_format)
    now = dt.datetime.now(tz=local_timezone())
    try:
        longest_options = build_options(days=90, until=iso_z(now))
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
    render(longest_result, longest_options, rows, "overview", output_format, output)


@app.command()
def overview(output_format: FormatOpt = "table", output: OutputOpt = None) -> None:
    """Show rolling 7/30/90 day usage."""
    _run_overview(output_format, output)


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
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
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
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
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
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
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
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
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
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
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
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
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
    default_model: DefaultModelOpt = "gpt-5.5",
    show_prompts: ShowPromptsOpt = False,
    offline: OfflineOpt = True,
    compact: CompactOpt = False,
    top_threads: TopThreadsOpt = 10,
) -> None:
    """Show recent rate-limit and credit samples."""
    _validate_format(output_format)
    options = _options(locals())
    result = load_usage(options)
    render_limits(result, options, output_format, output)


@app.command()
def doctor(
    session_root: SessionRootOpt = None,
    state_db: StateDbOpt = None,
    codex_config: CodexConfigOpt = None,
) -> None:
    """Check local Codex data paths."""
    try:
        options = build_options(
            days=1,
            session_root=session_root,
            state_db=state_db,
            codex_config=codex_config,
        )
    except ValueError as exc:
        raise _exit_error(str(exc)) from exc
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
        typer.Option("--format", "-f", help="table or json."),
    ] = "table",
) -> None:
    """Show the active rate card, sources, and age."""
    if output_format not in {"table", "json"}:
        raise _exit_error("--format must be one of: table, json")

    age = _rate_card_age_days()
    stale = age > 90

    if output_format == "json":
        import json as _json

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
        typer.echo(_json.dumps(payload, indent=2))
        return

    from rich.table import Table

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
def rates_refresh() -> None:
    """Refresh the embedded rate card from a URL (not yet implemented)."""
    raise _exit_error(
        "rates refresh is not yet implemented. Use --rates-file to override locally, "
        "or open an issue to request live refresh."
    )
