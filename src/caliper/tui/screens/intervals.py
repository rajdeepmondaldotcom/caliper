"""Intervals screen. Answers: what did each day, week, month cost."""

from __future__ import annotations

from textual.widgets import DataTable, Static, TabbedContent, TabPane

from caliper.tui.formatting import format_cost_usd_cell
from caliper.tui.screens._base import CaliperScreen
from caliper.tui.state import AppSnapshot

_COLUMNS = ("Date", "Top model", "Vendor", "Cost $", "Events")


class IntervalsScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Intervals"
    SCREEN_QUESTION = "What did each day, week, and month cost."

    DEFAULT_CSS = """
    IntervalsScreen TabbedContent { height: 1fr; }
    IntervalsScreen DataTable { height: 1fr; }
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
                f"[dim]Daily:[/dim] {len(snap.daily)}  "
                f"[dim]Weekly:[/dim] {len(snap.weekly)}  "
                f"[dim]Monthly:[/dim] {len(snap.monthly)}"
            )

    def middle(self):
        tabs = TabbedContent(id="interval-tabs")
        yield tabs

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ [ prev ]  [ ] next ]  [ esc home ]"

    def on_mount(self) -> None:
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        tabs = self.query_one("#interval-tabs", TabbedContent)
        for label, rows in (
            ("Daily", snap.daily if snap else ()),
            ("Weekly", snap.weekly if snap else ()),
            ("Monthly", snap.monthly if snap else ()),
        ):
            pane = TabPane(label)
            tabs.add_pane(pane)
            table = DataTable(cursor_type="row", zebra_stripes=True)
            table.add_columns(*_COLUMNS)
            for row in list(rows)[:50]:
                table.add_row(*_render_row(row))
            pane.mount(table)


def _render_row(item) -> tuple[str, ...]:
    breakdowns = getattr(item, "model_breakdowns", None) or {}
    if breakdowns:
        ranked = sorted(
            breakdowns.values(),
            key=lambda mb: mb.costs.cost_usd,
            reverse=True,
        )
        top_model = ranked[0].model if ranked else "-"
        vendor = getattr(ranked[0], "model_vendor", "unknown") if ranked else "-"
    else:
        models = sorted(getattr(item, "models", set()) or set())
        top_model = next(iter(models), "-")
        vendor = "-"
    return (
        item.label or item.key,
        top_model,
        vendor.title(),
        format_cost_usd_cell(item),
        f"{item.totals.events:,}",
    )
