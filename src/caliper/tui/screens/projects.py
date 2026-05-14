"""Projects screen. Answers: which working directory is the biggest spender."""

from __future__ import annotations

from textual.widgets import DataTable, Static

from caliper.tui.screens._base import CaliperScreen
from caliper.tui.state import AppSnapshot


class ProjectsScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Projects"
    SCREEN_QUESTION = "Which working directory is the biggest spender."

    DEFAULT_CSS = """
    ProjectsScreen Tree { height: 1fr; }
    ProjectsScreen DataTable { height: 1fr; }
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
        table = DataTable(id="project-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Project", "Top model", "Vendor", "Credits", "API $", "Events")
        yield table

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ enter drill ]  [ esc back ]"

    def on_mount(self) -> None:
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        from textual.css.query import NoMatches

        try:
            table = self.query_one("#project-table", DataTable)
        except NoMatches:
            return
        if snap is None or not snap.projects:
            table.add_row("(no projects yet)", "-", "-", "-", "-", "-")
            return
        for project in list(snap.projects)[:50]:
            breakdowns = getattr(project, "model_breakdowns", None) or {}
            if breakdowns:
                ranked = sorted(
                    breakdowns.values(),
                    key=lambda mb: float(mb.costs.api_dollars),
                    reverse=True,
                )
                top_model = ranked[0].model
                vendor = getattr(ranked[0], "model_vendor", "unknown").title()
            else:
                top_model = next(iter(sorted(getattr(project, "models", set()) or set())), "-")
                vendor = "-"
            table.add_row(
                (project.label or project.key)[:48],
                top_model,
                vendor,
                f"{float(project.costs.adjusted_credits):,.0f}",
                f"${float(project.costs.api_dollars):,.2f}",
                f"{project.totals.events:,}",
            )
