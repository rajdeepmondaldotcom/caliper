"""Forecast screen. Answers: where the trend lands at month end."""

from __future__ import annotations

from textual.widgets import Static

from caliper.tui.formatting import format_cost_usd
from caliper.tui.screens._base import CaliperScreen
from caliper.tui.widgets.sparkline import Sparkline


class ForecastScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Forecast"
    SCREEN_QUESTION = "Where the trend lands at month end."

    DEFAULT_CSS = """
    ForecastScreen Sparkline { height: 3; margin: 1 0; }
    """

    BINDINGS = [
        ("r", "refresh", "refresh"),
        ("escape", "app.pop_screen", "back"),
    ]

    def top(self):
        snap = getattr(self.app, "snapshot", None)
        yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}")
        if snap is not None:
            yield Static(f"[dim]Window:[/dim] {snap.scope.interval.label}")

    def middle(self):
        snap = getattr(self.app, "snapshot", None)
        if snap is None or not snap.daily:
            yield Static("[dim]Not enough daily data yet.[/dim]")
            return
        values = [item.costs.cost_usd for item in snap.daily[-30:]]
        series = [float(value) for value in values]
        yield Static("[dim]Last 30 days · Cost $[/dim]")
        yield Sparkline(series)
        total = sum(values, start=0)
        avg = total / max(len(series), 1)
        projected = avg * 30
        yield Static(
            f"\n[bold]Last 30 days total:[/bold] {format_cost_usd(total)}\n"
            f"[bold]Daily average:[/bold] {format_cost_usd(avg)}\n"
            f"[bold]Next-30 projection (linear):[/bold] {format_cost_usd(projected)}"
        )

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ esc back ]"
