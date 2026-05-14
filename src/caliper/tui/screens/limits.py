"""Limits screen. Answers: where the credit windows stand right now."""

from __future__ import annotations

from textual.widgets import Static

from caliper.tui.screens._base import CaliperScreen
from caliper.tui.widgets.window_panel import WindowPanel


class LimitsScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Limits"
    SCREEN_QUESTION = "How much of the 5h and weekly windows is left."

    DEFAULT_CSS = """
    LimitsScreen WindowPanel { margin: 0 1 1 0; }
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
        primary = getattr(snap, "primary_window", None) if snap else None
        secondary = getattr(snap, "secondary_window", None) if snap else None
        yield WindowPanel("Primary 5h", primary)
        yield WindowPanel("Secondary weekly", secondary)

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ esc back ]"
