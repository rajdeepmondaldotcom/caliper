"""What-if screen. Re-prices the window under hypothetical tier or model."""

from __future__ import annotations

from textual.widgets import Input, Static

from caliper.tui.screens._base import CaliperScreen


class WhatIfScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - What if"
    SCREEN_QUESTION = "What changes if you swap tier or model."

    BINDINGS = [
        ("r", "refresh", "refresh"),
        ("escape", "app.pop_screen", "back"),
    ]

    def top(self):
        yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}")

    def middle(self):
        yield Static("[dim]Hypothetical tier (e.g. standard, priority, flex):[/dim]")
        yield Input(placeholder="standard", id="tier-input")
        yield Static("[dim]Hypothetical model (must be in rate card):[/dim]")
        yield Input(placeholder="claude-sonnet-4.6", id="model-input")
        yield Static(
            "\n[dim]Press enter inside an input to apply the swap. "
            "Full delta lands in a follow-up commit.[/dim]"
        )

    def footer_pills(self) -> str:
        return "[ enter apply ]  [ esc back ]"
