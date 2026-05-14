"""Budgets screen. Answers: which budgets are about to breach."""

from __future__ import annotations

import datetime as dt

from textual.widgets import DataTable, Static

from caliper.budgets import evaluate, parse_budgets_table, usage_for_periods
from caliper.config import load_config
from caliper.timeutil import local_timezone
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
        alerts = self._alerts(snap)
        yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}")
        configured = len(alerts)
        actionable = sum(1 for alert in alerts if alert.severity != "ok")
        yield Static(f"[dim]Budgets:[/dim] {configured}   [dim]Actionable:[/dim] {actionable}")

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
        alerts = self._alerts(snap)
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

    @staticmethod
    def _alerts(snap):
        if snap is None or snap.load_result is None or snap.rate_card is None:
            return []
        raw = load_config().get("budgets") or {}
        budgets = parse_budgets_table(raw if isinstance(raw, dict) else {})
        if not budgets:
            return []
        now = dt.datetime.now(tz=local_timezone())
        usage = usage_for_periods(snap.load_result.events, snap.options, snap.rate_card, now)
        return evaluate(budgets, usage)
