"""Insights screen. Cards stack of voice-tuned heuristics."""

from __future__ import annotations

from textual.widgets import Static

from caliper.tui.screens._base import CaliperScreen
from caliper.tui.state import AppSnapshot

_SEVERITY_GLYPH = {"ok": ".", "info": "i", "warn": "!", "fail": "x", "breach": "X"}


class InsightsScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Insights"
    SCREEN_QUESTION = "What is worth noticing in this window."

    DEFAULT_CSS = """
    InsightsScreen .card {
        padding: 1 2;
        border: round $primary 40%;
        margin: 0 1 1 0;
    }
    """

    BINDINGS = [
        ("r", "refresh", "refresh"),
        ("escape", "app.pop_screen", "back"),
    ]

    def top(self):
        snap = getattr(self.app, "snapshot", None)
        yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}")
        if snap is not None:
            yield Static(
                f"[dim]Window:[/dim] {snap.scope.interval.label}   "
                f"[dim]Insights:[/dim] {len(snap.insights)}"
            )

    def middle(self):
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        if not snap or not snap.insights:
            yield Static("[dim]No insights surfaced yet.[/dim]")
            return
        for insight in snap.insights[:10]:
            glyph = _SEVERITY_GLYPH.get(insight.severity, "i")
            body = (
                f"[bold]{glyph}  {insight.title}[/bold]\n"
                f"{insight.detail}\n"
                f"[dim]{insight.action}[/dim]"
            )
            if getattr(insight, "next_command", ""):
                body += f"\n[dim]>>>[/dim] {insight.next_command}"
            yield Static(body, classes="card")

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ esc back ]"
