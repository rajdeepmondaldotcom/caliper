"""Models screen. Answers: which model + tier is bleeding the budget."""

from __future__ import annotations

from textual.widgets import DataTable, Static

from caliper.tui.formatting import format_cost_usd_cell
from caliper.tui.screens._base import CaliperScreen
from caliper.tui.state import AppSnapshot

_VENDOR_GLYPH = {
    "anthropic": "A",
    "openai": "O",
    "anysphere": "C",
    "google": "G",
    "mistral": "M",
    "meta": "L",
    "unknown": "?",
}


class ModelsScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Models"
    SCREEN_QUESTION = "Which model and tier is bleeding the budget."

    DEFAULT_CSS = """
    ModelsScreen DataTable { height: 1fr; }
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
                f"[dim]Model tiers:[/dim] {len(snap.models)}"
            )

    def middle(self):
        table = DataTable(id="models-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("V", "Model", "Tier", "Events", "Cost $")
        yield table

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ esc back ]"

    def on_mount(self) -> None:
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        from textual.css.query import NoMatches

        try:
            table = self.query_one("#models-table", DataTable)
        except NoMatches:
            return
        if snap is None or not snap.models:
            table.add_row("?", "(no models yet)", "-", "-", "-")
            return
        for row in list(snap.models)[:50]:
            breakdowns = list((getattr(row, "model_breakdowns", None) or {}).values())
            if breakdowns:
                breakdown = max(breakdowns, key=lambda mb: mb.costs.cost_usd)
                glyph = _VENDOR_GLYPH.get(getattr(breakdown, "model_vendor", "unknown"), "?")
                model = breakdown.model
                tier = breakdown.service_tier
            else:
                glyph = "?"
                model = next(iter(sorted(getattr(row, "models", set()) or set())), "-")
                tier = "-"
            table.add_row(
                glyph,
                model,
                tier,
                f"{row.totals.events:,}",
                format_cost_usd_cell(row),
            )
