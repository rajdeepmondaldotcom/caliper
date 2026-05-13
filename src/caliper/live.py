"""Live TUI for caliper. Re-parses JSONL on each tick (cache is Phase 3)."""

from __future__ import annotations

import datetime as dt
import select
import signal
import sys
import time
from dataclasses import dataclass

from rich.console import Console, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from caliper.aggregation import aggregate_total, event_cost
from caliper.humanize import sparkline
from caliper.models import LoadResult, RuntimeOptions
from caliper.parser import load_usage
from caliper.pricing import RateCard, load_rate_card
from caliper.render import pricing_status, pricing_warnings
from caliper.timeutil import local_timezone
from caliper.windows import (
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
    today_cache_savings: float = 0.0
    today_sparkline: str = ""
    refresh_ms: float = 0.0
    pricing_status: str = "exact"
    pricing_warnings: tuple[str, ...] = ()


@dataclass
class LiveLoopState:
    frame: LiveFrame
    show_help: bool = False
    paused: bool = False
    ticks: int = 0


def _window_subset(events, start: dt.datetime, end: dt.datetime):
    return [event for event in events if start <= event.timestamp < end]


def collect_frame(options: RuntimeOptions, now: dt.datetime | None = None) -> LiveFrame:
    """Load usage + compute one frame snapshot. Pure-ish (depends on parser + clock)."""
    started = time.perf_counter()
    result = load_usage(options)
    rate_card = load_rate_card(options)
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
        today_credits=float(today_total.costs.adjusted_credits),
        today_api_dollars=float(today_total.costs.api_dollars),
        week_credits=float(week_total.costs.adjusted_credits),
        primary=primary,
        secondary=secondary,
        plan_types=tuple(sorted(result.plan_types)),
        events_loaded=len(result.events),
        today_cache_savings=float(today_total.cache_savings.api_dollars),
        today_sparkline=_sparkline(_hourly_credit_series(today_events, rate_card, now)),
        refresh_ms=(time.perf_counter() - started) * 1000,
        pricing_status=pricing_status(today_total),
        pricing_warnings=tuple(pricing_warnings(today_total)),
    )


def _hourly_credit_series(events, rate_card: RateCard, now: dt.datetime) -> list[float]:
    local_now = now.astimezone(local_timezone())
    buckets = [0.0] * (local_now.hour + 1)
    for event in events:
        local_event = event.timestamp.astimezone(local_timezone())
        if local_event.date() != local_now.date():
            continue
        costs, _, _ = event_cost(rate_card, event)
        buckets[local_event.hour] += float(costs.adjusted_credits)
    return buckets


def _window_panel(label: str, state: WindowState, *, compact: bool = False) -> Panel:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(no_wrap=True, justify="right", style="dim")
    grid.add_column()
    bar = ProgressBar(total=100, completed=state.used_percent or 0, width=14 if compact else 24)
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
    if frame.today_cache_savings:
        grid.add_row("Cache saved", f"${frame.today_cache_savings:,.2f}")
    if frame.pricing_status != "exact":
        grid.add_row("Pricing", frame.pricing_status)
    for warning in frame.pricing_warnings[:2]:
        grid.add_row("Warning", warning)
    if frame.today_sparkline:
        grid.add_row("Today trend", frame.today_sparkline)
    grid.add_row("Refresh", f"{frame.refresh_ms:,.0f} ms")
    return Panel(grid, title="Usage", border_style="green")


def render_frame(
    frame: LiveFrame,
    show_help: bool = False,
    paused: bool = False,
    width: int | None = None,
) -> RenderableType:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
    )
    header_text = Text(
        f"Caliper — {frame.now.strftime('%Y-%m-%d %H:%M:%S %Z')}    "
        f"(q quit · ? help · r refresh · p {'resume' if paused else 'pause'})",
        style="bold white on blue",
    )
    layout["header"].update(Panel(header_text, border_style="blue"))
    body = Layout()
    if show_help:
        body.update(_help_panel())
    elif (width or 120) < 110:
        body.split_column(
            Layout(_usage_panel(frame), name="usage", size=10),
            Layout(_window_panel("Primary 5h", frame.primary, compact=True), name="primary"),
            Layout(
                _window_panel("Secondary weekly", frame.secondary, compact=True),
                name="secondary",
            ),
        )
    else:
        body.split_row(
            Layout(_usage_panel(frame), name="usage"),
            Layout(_window_panel("Primary 5h", frame.primary), name="primary"),
            Layout(_window_panel("Secondary weekly", frame.secondary), name="secondary"),
        )
    layout["body"].update(body)
    return layout


def _help_panel() -> Panel:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold")
    grid.add_column()
    grid.add_row("q", "quit")
    grid.add_row("?", "toggle this help")
    grid.add_row("r", "refresh immediately")
    grid.add_row("p", "pause or resume auto-refresh")
    grid.add_row("Ctrl-C", "quit")
    return Panel(grid, title="Live Help", border_style="blue")


def _sparkline(values: list[float]) -> str:
    # Kept as a thin alias for in-module callers and any external code
    # that imports the private name. New callers should import
    # ``caliper.humanize.sparkline`` directly.
    return sparkline(values)


def _read_key() -> str:
    if not sys.stdin.isatty():
        return ""
    readable, _, _ = select.select([sys.stdin], [], [], 0)
    if not readable:
        return ""
    return sys.stdin.read(1)


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
    try:
        target = console or Console()
        state = LiveLoopState(frame=collect_frame(options))
        width = target.size.width
        with Live(
            _render_live_state(state, width),
            console=target,
            refresh_per_second=4,
            screen=False,
        ) as live:
            _run_live_loop(live, state, options, interval, max_ticks, stop, width)
    finally:
        signal.signal(signal.SIGINT, original)


def _run_live_loop(
    live: Live,
    state: LiveLoopState,
    options: RuntimeOptions,
    interval: float,
    max_ticks: int | None,
    stop: dict,
    width: int,
) -> None:
    while not stop["flag"]:
        if _handle_live_key(state, options):
            break
        _sleep_one_tick(state, interval)
        if _should_stop(state, stop, max_ticks):
            break
        if _auto_refresh_enabled(state):
            state.frame = collect_frame(options)
        live.update(_render_live_state(state, width))


def _handle_live_key(state: LiveLoopState, options: RuntimeOptions) -> bool:
    key = _read_key()
    if key == "q":
        return True
    if key == "?":
        state.show_help = not state.show_help
    if key == "p":
        state.paused = not state.paused
    if key == "r" and not state.paused:
        state.frame = collect_frame(options)
    return False


def _sleep_one_tick(state: LiveLoopState, interval: float) -> None:
    time.sleep(interval)
    state.ticks += 1


def _should_stop(state: LiveLoopState, stop: dict, max_ticks: int | None) -> bool:
    if max_ticks is not None and state.ticks >= max_ticks:
        return True
    return bool(stop["flag"])


def _auto_refresh_enabled(state: LiveLoopState) -> bool:
    return not state.paused and not state.show_help


def _render_live_state(state: LiveLoopState, width: int) -> RenderableType:
    return render_frame(
        state.frame,
        show_help=state.show_help,
        paused=state.paused,
        width=width,
    )
