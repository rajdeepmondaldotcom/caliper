"""Models screen. Answers: which model + tier is bleeding the budget."""

from __future__ import annotations

from textual.widgets import Static

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
    ModelsScreen #models-table { height: 1fr; overflow-y: auto; }
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
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        if snap is None or not snap.models:
            yield Static("(no models yet)", id="models-table")
            return
        lines = [_format_model_header()]
        for row in list(snap.models)[:50]:
            lines.append(_format_model_row(row))
        yield Static("\n".join(lines), id="models-table", markup=False)

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ esc back ]"


def _render_model_row(row) -> tuple[str, str, str, str, str]:
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
    return glyph, model, tier, f"{row.totals.events:,}", format_cost_usd_cell(row)


def _format_model_header() -> str:
    return f"{'Model':<22} {'Tier':<10} {'Events':>8} {'Cost $':>10} {'V':<2}"


def _format_model_row(row) -> str:
    glyph, model, tier, events, cost = _render_model_row(row)
    return f"{model[:22]:<22} {tier[:10]:<10} {events:>8} {cost:>10} {glyph:<2}"
