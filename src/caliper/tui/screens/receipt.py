"""Receipt screen. Shareable summary of the window."""

from __future__ import annotations

from textual.widgets import Static

from caliper.tui.screens._base import CaliperScreen


class ReceiptScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Receipt"
    SCREEN_QUESTION = "What this window looks like as a receipt."

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
        if snap is None or snap.overview_total is None:
            yield Static("[dim]Waiting for the first load.[/dim]")
            return
        total = snap.overview_total
        lines = [
            "[bold]Caliper receipt[/bold]",
            "",
            f"Window: {snap.scope.interval.label}",
            f"Events: {total.totals.events:,}",
            f"Tokens: {total.totals.total_tokens:,}",
            f"Cost (API $): ${float(total.costs.api_dollars):,.2f}",
            f"Credits: {float(total.costs.adjusted_credits):,.2f}",
            "",
            "[dim]Press y to copy. Clipboard wiring lands in a follow-up.[/dim]",
        ]
        yield Static("\n".join(lines))

    def footer_pills(self) -> str:
        return "[ y copy ]  [ esc back ]"
