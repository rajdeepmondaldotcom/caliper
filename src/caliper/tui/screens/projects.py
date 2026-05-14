"""Projects screen. Answers: which working directory is the biggest spender."""

from __future__ import annotations

from textual.widgets import Static

from caliper.humanize import short_table_label
from caliper.tui.formatting import format_cost_usd_cell, format_vendor_label
from caliper.tui.screens._base import CaliperScreen
from caliper.tui.state import AppSnapshot


def _project_table_label(project: object) -> str:
    label = short_table_label(getattr(project, "label", "") or getattr(project, "key", ""))
    return (label or "Unknown Project")[:48]


class ProjectsScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Projects"
    SCREEN_QUESTION = "Which working directory is the biggest spender."

    DEFAULT_CSS = """
    ProjectsScreen #project-table { height: 1fr; overflow-y: auto; }
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
                f"[dim]Projects:[/dim] {len(snap.projects)}"
            )

    def middle(self):
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        if snap is None or not snap.projects:
            yield Static("(no projects yet)", id="project-table")
            return
        lines = [_format_project_header()]
        for project in list(snap.projects)[:50]:
            lines.append(_format_project_row(project))
        yield Static("\n".join(lines), id="project-table", markup=False)

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ esc back ]"


def _render_project_row(project) -> tuple[str, str, str, str, str]:
    breakdowns = getattr(project, "model_breakdowns", None) or {}
    if breakdowns:
        ranked = sorted(
            breakdowns.values(),
            key=lambda mb: mb.costs.cost_usd,
            reverse=True,
        )
        top_model = ranked[0].model
        vendor = format_vendor_label(getattr(ranked[0], "model_vendor", "unknown"))
    else:
        top_model = next(iter(sorted(getattr(project, "models", set()) or set())), "-")
        vendor = "-"
    return (
        _project_table_label(project),
        top_model,
        vendor,
        format_cost_usd_cell(project),
        f"{project.totals.events:,}",
    )


def _format_project_header() -> str:
    return f"{'Project':<24} {'Cost $':>10} {'Events':>8} {'Top model':<18} {'Vendor':<10}"


def _format_project_row(project) -> str:
    label, top_model, vendor, cost, events = _render_project_row(project)
    return f"{label[:24]:<24} {cost:>10} {events:>8} {top_model[:18]:<18} {vendor[:10]:<10}"
