"""Home screen — answer 'what did I spend recently and is anything wrong?'."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from caliper.tui.formatting import format_cost_usd_cell
from caliper.tui.state import AppSnapshot
from caliper.tui.widgets.app_header import CaliperHeader
from caliper.tui.widgets.cost_card import CostCard
from caliper.tui.widgets.window_panel import WindowPanel


class HomeScreen(Screen):
    """Default screen. Three cost windows + limits + insights + recent."""

    BINDINGS = []

    DEFAULT_CSS = """
    HomeScreen #home-body { height: 1fr; }
    HomeScreen #cards { height: 7; }
    HomeScreen #windows { height: 9; }
    HomeScreen #home-footer {
        height: 1;
        padding: 0 1;
        color: $foreground 70%;
    }
    HomeScreen #insights {
        padding: 1 2;
        border: round $primary 40%;
        margin: 0 1 1 0;
    }
    HomeScreen .empty {
        content-align: center middle;
        width: 1fr; height: 1fr;
        color: $foreground 60%;
    }
    """

    def compose(self) -> ComposeResult:
        yield CaliperHeader(show_clock=True)
        yield Vertical(
            Horizontal(id="cards"),
            Horizontal(id="windows"),
            Static("", id="insights"),
            Static("", id="recent"),
            Static(
                "[ 0 receipt ] [ i insights ] [ ? help ] [ r refresh ] [ q quit ]",
                id="home-footer",
            ),
            id="home-body",
        )

    def on_mount(self) -> None:
        self.call_after_refresh(
            lambda: self.update_from_snapshot(self.app.snapshot)  # type: ignore[attr-defined]
        )

    def update_from_snapshot(self, snapshot: AppSnapshot) -> None:
        from textual.css.query import NoMatches

        try:
            cards = self.query_one("#cards", Horizontal)
        except NoMatches:
            # Compose has not yet completed; the next snapshot tick
            # will redraw after the layout settles.
            return
        cards.remove_children()
        if not snapshot.overview_windows:
            cards.mount(Static(self._empty_message(snapshot), classes="empty"))
        else:
            from caliper.render import vendor_chip

            for window in snapshot.overview_windows:
                series = self._series_for(snapshot, window.label)
                cards.mount(
                    CostCard(
                        label=self._card_label(window.label),
                        cost_usd=float(window.costs.cost_usd),
                        series=series,
                        vendors=vendor_chip(window),
                    )
                )

        windows = self.query_one("#windows", Horizontal)
        windows.remove_children()
        windows.mount(WindowPanel("Primary 5h", snapshot.primary_window))
        windows.mount(WindowPanel("Secondary weekly", snapshot.secondary_window))

        insights_panel = self.query_one("#insights", Static)
        if snapshot.insights:
            insights_panel.update(self._render_insights(snapshot))
        else:
            insights_panel.update("[dim]No insights surfaced yet.[/dim]")

        recent_panel = self.query_one("#recent", Static)
        recent_panel.update(self._render_recent(snapshot))

    @staticmethod
    def _empty_message(snapshot: AppSnapshot) -> str:
        if snapshot.refresh_error:
            return f"[red]error:[/red] {snapshot.refresh_error}"
        if snapshot.is_loading():
            return "Reading sessions…"
        return (
            "Nothing parsed yet.\n\n"
            "Run a coding session in Codex, Claude Code, Cursor, or Aider —\n"
            "or relaunch with `caliper tui --demo` to explore with sample data."
        )

    @staticmethod
    def _series_for(snapshot: AppSnapshot, label: str) -> list[float]:
        if not snapshot.daily:
            return []
        if "7" in label:
            window = snapshot.daily[-7:]
        elif "30" in label:
            window = snapshot.daily[-30:]
        else:
            window = snapshot.daily[-90:]
        return [float(item.costs.cost_usd) for item in window]

    @staticmethod
    def _card_label(label: str) -> str:
        if "7" in label:
            return "7d"
        if "30" in label:
            return "30d"
        if "90" in label:
            return "90d"
        return label

    @staticmethod
    def _render_insights(snapshot: AppSnapshot) -> str:
        lines = []
        for item in snapshot.insights[:4]:
            severity = getattr(item, "severity", "info")
            title = getattr(item, "title", "")
            detail = getattr(item, "detail", "")
            badge = {"info": "•", "warn": "▲", "fail": "■"}.get(severity, "•")
            lines.append(f"{badge}  [b]{title}[/b] — {detail}")
        return "\n".join(lines) or "No insights surfaced yet."

    @staticmethod
    def _render_recent(snapshot: AppSnapshot) -> str:
        if not snapshot.sessions:
            return "[dim]No sessions in the active window.[/dim]"
        from caliper.render import vendor_chip

        lines = ["[b]Recent sessions[/b]"]
        for session in snapshot.sessions[:5]:
            chip = vendor_chip(session)
            chip_part = f"  [dim]{chip}[/dim]" if chip else ""
            lines.append(
                f"  {session.label or session.key}   {format_cost_usd_cell(session)}{chip_part}"
            )
        return "\n".join(lines)
