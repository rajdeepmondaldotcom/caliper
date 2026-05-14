"""Forecast screen. Answers: where the trend lands at month end."""

from __future__ import annotations

from textual.widgets import Static

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
        series = [float(item.costs.api_dollars) for item in snap.daily[-30:]]
        yield Static("[dim]Last 30 days · API $[/dim]")
        yield Sparkline(series)
        total = sum(series)
        avg = total / max(len(series), 1)
        projected = avg * 30
        yield Static(
            f"\n[bold]Last 30 days total:[/bold] ${total:,.2f}\n"
            f"[bold]Daily average:[/bold] ${avg:,.2f}\n"
            f"[bold]Next-30 projection (linear):[/bold] ${projected:,.2f}"
        )

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ esc back ]"
