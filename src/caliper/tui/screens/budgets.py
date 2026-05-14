"""Budgets screen. Answers: which budgets are about to breach."""

from __future__ import annotations

from textual.widgets import DataTable, Static

from caliper.tui.screens._base import CaliperScreen


class BudgetsScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Budgets"
    SCREEN_QUESTION = "Which budgets are about to breach."

    DEFAULT_CSS = """
    BudgetsScreen DataTable { height: 1fr; }
    """

    BINDINGS = [
        ("r", "refresh", "refresh"),
        ("escape", "app.pop_screen", "back"),
    ]

    def top(self):
        snap = getattr(self.app, "snapshot", None)
        alerts = list(getattr(snap, "budget_alerts", []) or [])
        yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}")
        yield Static(f"[dim]Alerts:[/dim] {len(alerts)}")

    def middle(self):
        table = DataTable(id="budget-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Severity", "Period", "Metric", "Used", "Cap", "Used %")
        yield table

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ esc back ]"

    def on_mount(self) -> None:
        from textual.css.query import NoMatches

        try:
            table = self.query_one("#budget-table", DataTable)
        except NoMatches:
            return
        snap = getattr(self.app, "snapshot", None)
        alerts = list(getattr(snap, "budget_alerts", []) or [])
        if not alerts:
            table.add_row(".", "(no budgets configured)", "", "", "", "")
            return
        for alert in alerts:
            table.add_row(
                alert.severity,
                alert.budget.period,
                alert.budget.metric,
                f"{alert.used:,.0f}",
                f"{alert.budget.limit:,.0f}",
                f"{alert.used_percent:.1f}%",
            )
