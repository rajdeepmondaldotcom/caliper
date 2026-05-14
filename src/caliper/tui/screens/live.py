"""Live screen. Shows the current minute of usage."""

from __future__ import annotations

from textual.widgets import Static

from caliper.tui.formatting import format_cost_usd_cell
from caliper.tui.screens._base import CaliperScreen
from caliper.tui.widgets.sparkline import Sparkline


class LiveScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Live"
    SCREEN_QUESTION = "What is happening right now."

    DEFAULT_CSS = """
    LiveScreen Sparkline { height: 3; }
    """

    BINDINGS = [
        ("r", "refresh", "refresh"),
        ("escape", "app.pop_screen", "back"),
    ]

    def top(self):
        snap = getattr(self.app, "snapshot", None)
        yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}")
        if snap is not None and snap.refresh_completed_at:
            yield Static(f"[dim]Refreshed:[/dim] {snap.refresh_completed_at:%H:%M:%S}")

    def middle(self):
        snap = getattr(self.app, "snapshot", None)
        if snap is None or not snap.daily:
            yield Static("[dim]Waiting for the first load.[/dim]")
            return
        recent = [float(item.costs.cost_usd) for item in snap.daily[-7:]]
        yield Static("[dim]Last 7 days · Cost $[/dim]")
        yield Sparkline(recent)
        if snap.overview_total is not None:
            yield Static(
                f"\n[bold]Window cost:[/bold] "
                f"{format_cost_usd_cell(snap.overview_total)}\n"
                f"[bold]Events:[/bold] {snap.overview_total.totals.events:,}"
            )

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ esc back ]"
