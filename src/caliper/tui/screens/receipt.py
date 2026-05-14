"""Receipt screen. Shareable summary of the window."""

from __future__ import annotations

from textual.widgets import Static

from caliper.tui.formatting import format_cost_usd_cell
from caliper.tui.screens._base import CaliperScreen


class ReceiptScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Receipt"
    SCREEN_QUESTION = "What this window looks like as a receipt."

    BINDINGS = [
        ("r", "refresh", "refresh"),
        ("y", "copy", "copy"),
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
        yield Static(self._receipt_text(snap, markup=True))

    def footer_pills(self) -> str:
        return "[ y copy ]  [ esc back ]"

    def action_copy(self) -> None:
        snap = getattr(self.app, "snapshot", None)
        if snap is None or snap.overview_total is None:
            self.app.notify("No receipt loaded yet.")
            return
        self.app.copy_to_clipboard(self._receipt_text(snap, markup=False))
        self.app.notify("Receipt copied.")

    @staticmethod
    def _receipt_text(snap, *, markup: bool) -> str:
        total = snap.overview_total
        if total is None:
            return "Waiting for the first load."
        title = "[bold]Caliper receipt[/bold]" if markup else "Caliper receipt"
        return "\n".join(
            [
                title,
                "",
                f"Window: {snap.scope.interval.label}",
                f"Events: {total.totals.events:,}",
                f"Tokens: {total.totals.total_tokens:,}",
                f"Cost: {format_cost_usd_cell(total)}",
            ]
        )
