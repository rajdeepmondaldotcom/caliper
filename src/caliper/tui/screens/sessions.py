"""Sessions screen. Answers: which sessions cost the most this window."""

from __future__ import annotations

from collections.abc import Iterable

from textual.css.query import NoMatches
from textual.widgets import DataTable, Static, Tab, Tabs

from caliper.tui.formatting import format_cost_usd_cell
from caliper.tui.screens._base import CaliperScreen
from caliper.tui.state import AppSnapshot

_VENDOR_LABELS: dict[str, str] = {
    "all": "All",
    "openai-codex": "Codex",
    "claude-code": "Claude",
}


class SessionsScreen(CaliperScreen):
    """Sortable DataTable of recent sessions, scoped by tool vendor.

    Top band: scope chip + total event count.
    Middle band: vendor Tabs row + DataTable.
    Footer: r refresh, esc home.
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
        ("escape", "app.pop_screen", "back"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._active_vendor: str = "all"
        self._compact_table = False

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
        if self._active_vendor not in vendors:
            self._active_vendor = "all"
        tabs = Tabs(
            *(Tab(_VENDOR_LABELS.get(v, v.title()), id=f"v-{v}") for v in vendors), id="vendor-tabs"
        )
        yield tabs
        table = DataTable(id="sessions-table", cursor_type="row", zebra_stripes=True)
        self._compact_table = self._is_compact_view()
        if self._compact_table:
            table.add_column("Session", width=24)
            table.add_column("Model", width=16)
            table.add_column("Cost $", width=10)
        else:
            table.add_column("When", width=32)
            table.add_column("Vendor", width=13)
            table.add_column("Model", width=20)
            table.add_column("Tier", width=11)
            table.add_column("Tokens", width=12)
            table.add_column("Cost $", width=10)
        rows = list(
            self._rows_for(
                snap.sessions if snap else (),
                vendor=self._active_vendor,
                compact=self._compact_table,
            )
        )
        if rows:
            for row in rows[:50]:
                table.add_row(*row)
        else:
            table.add_row(*self._empty_row())
        yield table

    def footer_pills(self) -> str:
        return "[ ctrl+p palette ]  [ r refresh ]  [ esc home ]"

    # ------------------------------------------------------------------ hooks
    def on_tabs_tab_activated(self, event) -> None:
        new_vendor = event.tab.id.removeprefix("v-") if event.tab and event.tab.id else "all"
        self._active_vendor = new_vendor
        self._refresh_table()

    def update_from_snapshot(self, _snapshot) -> None:
        self._refresh_table()

    def action_refresh(self) -> None:
        if hasattr(self.app, "action_refresh"):
            self.app.action_refresh()

    # ------------------------------------------------------------------ helpers
    def _refresh_table(self) -> None:
        snap: AppSnapshot | None = getattr(self.app, "snapshot", None)
        try:
            table = self.query_one("#sessions-table", DataTable)
        except NoMatches:
            return
        table.clear()
        rows = list(
            self._rows_for(
                snap.sessions if snap else (),
                vendor=self._active_vendor,
                compact=self._compact_table,
            )
        )
        if rows:
            for row in rows[:50]:
                table.add_row(*row)
        else:
            table.add_row(*self._empty_row())

    def _rows_for(self, sessions: Iterable, *, vendor: str, compact: bool = False):
        for session in sessions:
            session_vendors = getattr(session, "vendors", set()) or set()
            if vendor != "all" and vendor not in session_vendors:
                continue
            label = (session.label or session.key or "")[: (28 if compact else 40)]
            model = self._dominant_model(session)
            if compact:
                yield label, model, format_cost_usd_cell(session)
                continue
            tier = ", ".join(sorted(getattr(session, "service_tiers", set()) or {"-"}))[:14]
            tokens = getattr(session.totals, "total_tokens", 0)
            v = ", ".join(sorted(session_vendors)) or "-"
            yield label, v, model, tier, f"{tokens:,}", format_cost_usd_cell(session)

    def _empty_row(self) -> tuple[str, ...]:
        if self._compact_table:
            return ("(no sessions)", "", "")
        return ("(no sessions)", "", "", "", "", "")

    def _is_compact_view(self) -> bool:
        size = getattr(self.app, "size", None)
        width = getattr(size, "width", 100) if size is not None else 100
        return width < 72

    @staticmethod
    def _dominant_model(session) -> str:
        breakdowns = getattr(session, "model_breakdowns", None) or {}
        if breakdowns:
            ranked = sorted(
                breakdowns.values(),
                key=lambda mb: mb.costs.cost_usd,
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
