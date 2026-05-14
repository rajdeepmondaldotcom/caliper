"""Doctor screen. Answers: what is broken in the environment."""

from __future__ import annotations

from textual.widgets import DataTable, Static

from caliper.tui.screens._base import CaliperScreen


class DoctorScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Doctor"
    SCREEN_QUESTION = "What is broken in the environment."

    DEFAULT_CSS = """
    DoctorScreen DataTable { height: 1fr; }
    """

    BINDINGS = [
        ("r", "refresh", "refresh"),
        ("escape", "app.pop_screen", "back"),
    ]

    def top(self):
        yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}")

    def middle(self):
        table = DataTable(id="doctor-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Status", "Check", "Detail")
        snap = getattr(self.app, "snapshot", None)
        if snap is None or snap.load_result is None:
            table.add_row("...", "Waiting for first load", "")
        else:
            try:
                from caliper.health import build_health_report
                from caliper.vendors import vendor_file_count

                checks = build_health_report(
                    options=snap.options,
                    session_file_count=vendor_file_count(snap.options),
                    result=snap.load_result,
                )
            except Exception as exc:  # pragma: no cover - defensive
                table.add_row("x", "Doctor failed to run", str(exc))
            else:
                for check in checks:
                    glyph = {"ok": ".", "warn": "!", "fail": "x"}.get(check.status, "?")
                    table.add_row(glyph, check.label, check.detail[:80])
        yield table

    def footer_pills(self) -> str:
        return "[ r refresh ]  [ esc back ]"
