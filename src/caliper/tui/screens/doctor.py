"""Doctor screen. Answers: what is broken in the environment."""

from __future__ import annotations

from pathlib import Path

from textual.widgets import DataTable, Static

from caliper.tui.screens._base import CaliperScreen

_PATH_CHECK_LABELS = {"Session root", "State DB", "Codex config", "Rates file", "Parse cache"}


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
        snap = getattr(self.app, "snapshot", None)
        if snap is not None and snap.options.show_paths:
            mode = "Local paths visible. Press p to redact."
        else:
            mode = "Local paths redacted. Press p to reveal."
        yield Static(
            f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}\n[dim]{mode}[/dim]"
        )

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
                    table.add_row(
                        glyph,
                        check.label,
                        _doctor_detail(check.label, check.detail, snap.options.show_paths),
                    )
        yield table

    def footer_pills(self) -> str:
        return "[ p redact ]  [ r refresh ]  [ esc back ]"

    def update_from_snapshot(self, _snapshot) -> None:
        self.refresh(recompose=True)


def _doctor_detail(label: str, detail: str, show_paths: bool) -> str:
    if show_paths or label not in _PATH_CHECK_LABELS:
        return detail[:80]
    if label == "Rates file" and detail == "using embedded rate card":
        return detail
    if label == "State DB readable":
        return detail
    return _redact_path_detail(detail)[:80]


def _redact_path_detail(detail: str) -> str:
    if not detail:
        return ""
    if " (" in detail:
        path, suffix = detail.split(" (", 1)
        return f"{_path_basename(path)} ({suffix}"
    if " unreadable:" in detail:
        path, suffix = detail.split(" unreadable:", 1)
        return f"{_path_basename(path)} unreadable:{suffix}"
    if detail.endswith(" (not created yet)"):
        return f"{_path_basename(detail.removesuffix(' (not created yet)'))} (not created yet)"
    return _path_basename(detail)


def _path_basename(value: str) -> str:
    return Path(value).name or "<redacted-path>"
