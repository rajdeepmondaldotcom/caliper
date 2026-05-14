"""Sessions screen. Answers: which sessions cost the most this window."""

from __future__ import annotations

from typing import Iterable

from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static, Tabs, Tab

from caliper.tui.screens._base import CaliperScreen
from caliper.tui.state import AppSnapshot

_VENDOR_LABELS: dict[str, str] = {
    "all": "All",
    "openai-codex": "Codex",
    "claude-code": "Claude",
    "cursor": "Cursor",
    "aider": "Aider",
}


class SessionsScreen(CaliperScreen):
    """Sortable DataTable of recent sessions, scoped by tool vendor.

    Top band: scope chip + total event count.
    Middle band: vendor Tabs row + DataTable.
    Footer: r refresh, / filter, e export, esc home.
    """

    SCREEN_TITLE = "Caliper - Sessions"
    SCREEN_QUESTION = "Which sessions cost the most this window."

    DEFAULT_CSS = """
    SessionsScreen #vendor-tabs {
        height: 3;
        margin-bottom: 1;
    }
    SessionsScreen DataTable {
        height: 1fr;
    }
    SessionsScreen #scope-line {
        color: $foreground 70%;
    }
    """

    BINDINGS = [
        ("r", "refresh", "refresh"),
        ("slash", "focus_filter", "filter"),
        ("e", "export", "export"),
        ("escape", "app.pop_screen", "back"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._active_vendor: str = "all"

    # ------------------------------------------------------------------ slots
    def top(self):
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        if snap is None:
            yield Static("[bold]Caliper - Sessions[/bold]   loading...")
            return
        chip = self._scope_chip(snap)
        yield Static(f"[bold]Caliper - Sessions[/bold]   {self.SCREEN_QUESTION}")
        yield Static(chip, id="scope-line")

    def middle(self):
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        vendors = self._vendors_with_data(snap)
        tabs = Tabs(*(Tab(_VENDOR_LABELS.get(v, v.title()), id=f"v-{v}") for v in vendors), id="vendor-tabs")
        yield tabs
        table = DataTable(id="sessions-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("When", "Vendor", "Model", "Tier", "Tokens", "API $")
        yield table

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ / filter ]  [ e export ]  [ esc home ]"

    # ------------------------------------------------------------------ hooks
    def on_mount(self) -> None:
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        self._populate_table(snap, vendor="all")

    def on_tabs_tab_activated(self, event) -> None:
        new_vendor = event.tab.id.removeprefix("v-") if event.tab and event.tab.id else "all"
        self._active_vendor = new_vendor
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        self._populate_table(snap, vendor=new_vendor)

    def action_refresh(self) -> None:
        if hasattr(self.app, "action_refresh"):
            self.app.action_refresh()

    def action_export(self) -> None:
        self.app.notify("Receipt export lands in B-11.", timeout=3)

    def action_focus_filter(self) -> None:
        self.app.notify("Filter input lands in the next sessions revision.", timeout=3)

    # ------------------------------------------------------------------ helpers
    def _populate_table(self, snap: AppSnapshot | None, *, vendor: str) -> None:
        from textual.css.query import NoMatches

        try:
            table = self.query_one("#sessions-table", DataTable)
        except NoMatches:
            return
        table.clear()
        if snap is None or not snap.sessions:
            table.add_row("(no sessions)", "", "", "", "", "")
            return
        rows = list(self._rows_for(snap.sessions, vendor=vendor))
        for row in rows[:50]:  # cap at 50 per the UX standard
            table.add_row(*row)

    def _rows_for(self, sessions: Iterable, *, vendor: str):
        for session in sessions:
            session_vendors = getattr(session, "vendors", set()) or set()
            if vendor != "all" and vendor not in session_vendors:
                continue
            label = (session.label or session.key or "")[:40]
            model = self._dominant_model(session)
            tier = ", ".join(sorted(getattr(session, "service_tiers", set()) or {"-"}))[:14]
            tokens = getattr(session.totals, "total_tokens", 0)
            api = float(session.costs.api_dollars)
            v = ", ".join(sorted(session_vendors)) or "-"
            yield label, v, model, tier, f"{tokens:,}", f"${api:,.2f}"

    @staticmethod
    def _dominant_model(session) -> str:
        breakdowns = getattr(session, "model_breakdowns", None) or {}
        if breakdowns:
            ranked = sorted(
                breakdowns.values(),
                key=lambda mb: float(mb.costs.api_dollars),
                reverse=True,
            )
            return ranked[0].model if ranked else "-"
        models = getattr(session, "models", set()) or set()
        return next(iter(sorted(models)), "-")

    @staticmethod
    def _vendors_with_data(snap: AppSnapshot | None) -> list[str]:
        if snap is None or not snap.sessions:
            return ["all"]
        seen: set[str] = set()
        for session in snap.sessions:
            seen |= getattr(session, "vendors", set()) or set()
        return ["all", *sorted(seen)]

    @staticmethod
    def _scope_chip(snap: AppSnapshot) -> str:
        interval = snap.scope.interval
        return (
            f"[dim]Window:[/dim] {interval.label}   "
            f"[dim]Events:[/dim] {sum(int(s.totals.events) for s in snap.sessions):,}   "
            f"[dim]Showing top 50[/dim]"
        )
