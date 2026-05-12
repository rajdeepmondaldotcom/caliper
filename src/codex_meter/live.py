"""Live TUI for codex-meter. Re-parses JSONL on each tick (cache is Phase 3)."""

from __future__ import annotations

import datetime as dt
import signal
import time
from dataclasses import dataclass

from rich.console import Console, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from codex_meter.aggregation import aggregate_total
from codex_meter.models import LoadResult, RuntimeOptions
from codex_meter.parser import load_usage
from codex_meter.pricing import RateCard
from codex_meter.timeutil import local_timezone
from codex_meter.windows import (
    WindowState,
    compute_window_state,
    format_burn_rate,
    format_seconds_remaining,
)


@dataclass(frozen=True)
class LiveFrame:
    now: dt.datetime
    today_credits: float
    today_api_dollars: float
    week_credits: float
    primary: WindowState
    secondary: WindowState
    plan_types: tuple[str, ...]
    events_loaded: int


def _window_subset(events, start: dt.datetime, end: dt.datetime):
    return [event for event in events if start <= event.timestamp < end]


def collect_frame(options: RuntimeOptions, now: dt.datetime | None = None) -> LiveFrame:
    """Load usage + compute one frame snapshot. Pure-ish (depends on parser + clock)."""
    result = load_usage(options)
    rate_card = RateCard.load(options.rates_file, options.pricing_mode)
    now = now or dt.datetime.now(tz=local_timezone())
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - dt.timedelta(days=7)

    today_events = _window_subset(result.events, today_start, now)
    week_events = _window_subset(result.events, week_start, now)

    today_result = LoadResult(
        events=today_events,
        duplicates=0,
        tier_sources=result.tier_sources,
        plan_types=result.plan_types,
        credit_samples=[],
        warnings=[],
    )
    week_result = LoadResult(
        events=week_events,
        duplicates=0,
        tier_sources=result.tier_sources,
        plan_types=result.plan_types,
        credit_samples=[],
        warnings=[],
    )

    today_total = aggregate_total(today_result, options, label="Today", rate_card=rate_card)
    week_total = aggregate_total(week_result, options, label="Last 7 days", rate_card=rate_card)

    primary = compute_window_state(result.credit_samples, now, "primary")
    secondary = compute_window_state(result.credit_samples, now, "secondary")

    return LiveFrame(
        now=now,
        today_credits=today_total.costs.adjusted_credits,
        today_api_dollars=today_total.costs.api_dollars,
        week_credits=week_total.costs.adjusted_credits,
        primary=primary,
        secondary=secondary,
        plan_types=tuple(sorted(result.plan_types)),
        events_loaded=len(result.events),
    )


def _window_panel(label: str, state: WindowState) -> Panel:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(no_wrap=True, justify="right", style="dim")
    grid.add_column()
    bar = ProgressBar(total=100, completed=state.used_percent or 0, width=24)
    grid.add_row("Used", bar)
    grid.add_row(
        "Percent",
        f"{state.used_percent:.1f}%" if state.used_percent is not None else "—",
    )
    grid.add_row("Reset in", format_seconds_remaining(state.seconds_remaining))
    if state.reset_at is not None:
        local = state.reset_at.astimezone(local_timezone())
        grid.add_row("Reset at", local.strftime("%Y-%m-%d %H:%M:%S %Z"))
    grid.add_row("Burn rate", format_burn_rate(state.burn_rate_per_hour))
    if state.eta_to_100 is not None:
        eta_local = state.eta_to_100.astimezone(local_timezone())
        grid.add_row("Hits 100% by", eta_local.strftime("%Y-%m-%d %H:%M"))
    title = label
    if state.window_minutes:
        title = f"{label} ({state.window_minutes}m)"
    border = "red" if (state.used_percent or 0) >= 80 else "cyan"
    return Panel(grid, title=title, border_style=border)


def _usage_panel(frame: LiveFrame) -> Panel:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(no_wrap=True, justify="right", style="dim")
    grid.add_column()
    grid.add_row(
        "Today",
        f"{frame.today_credits:,.2f} credits  /  ${frame.today_api_dollars:,.2f}",
    )
    grid.add_row("Last 7d", f"{frame.week_credits:,.2f} credits")
    grid.add_row("Events loaded", f"{frame.events_loaded:,}")
    if frame.plan_types:
        grid.add_row("Plan", ", ".join(frame.plan_types))
    return Panel(grid, title="Usage", border_style="green")


def render_frame(frame: LiveFrame) -> RenderableType:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
    )
    header_text = Text(
        f"Codex Meter — {frame.now.strftime('%Y-%m-%d %H:%M:%S %Z')}    (Ctrl-C to quit)",
        style="bold white on blue",
    )
    layout["header"].update(Panel(header_text, border_style="blue"))
    body = Layout()
    body.split_row(
        Layout(_usage_panel(frame), name="usage"),
        Layout(_window_panel("Primary 5h", frame.primary), name="primary"),
        Layout(_window_panel("Secondary weekly", frame.secondary), name="secondary"),
    )
    layout["body"].update(body)
    return layout


def run_live(
    options: RuntimeOptions,
    interval: float = 2.0,
    console: Console | None = None,
    max_ticks: int | None = None,
) -> None:
    """Start the TUI. Loops until SIGINT (or `max_ticks` for tests)."""
    stop = {"flag": False}

    def _on_signal(*_: object) -> None:
        stop["flag"] = True

    original = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _on_signal)
    ticks = 0
    try:
        target = console or Console()
        frame = collect_frame(options)
        with Live(
            render_frame(frame),
            console=target,
            refresh_per_second=4,
            screen=False,
        ) as live:
            while not stop["flag"]:
                time.sleep(interval)
                ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    break
                if stop["flag"]:
                    break
                live.update(render_frame(collect_frame(options)))
    finally:
        signal.signal(signal.SIGINT, original)
