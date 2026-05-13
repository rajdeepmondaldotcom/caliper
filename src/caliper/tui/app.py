"""Caliper Textual application shell.

The real screens, widgets, and themes land in later commits. This file
provides the minimal mountable surface so ``caliper tui`` boots and
the rest of the package can hang off it.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static

from caliper.config import TuiConfig, load_config, load_tui_config
from caliper.models import RuntimeOptions


class CaliperApp(App):
    """Minimal app shell — themes, bindings, and home placeholder.

    Subsequent commits replace the placeholder body with real screens
    and widgets. Until then this is enough to verify the install
    surface and the boot path end-to-end.
    """

    CSS_PATH = Path(__file__).parent / "tcss" / "base.tcss"
    TITLE = "Caliper"

    BINDINGS = [
        Binding("q", "quit", "quit", show=True, priority=True),
        Binding("question_mark", "show_help", "help"),
        Binding("r", "refresh", "refresh"),
        Binding("t", "cycle_theme", "theme"),
    ]

    def __init__(
        self,
        options: RuntimeOptions,
        *,
        demo: bool = False,
        tui_config: TuiConfig | None = None,
    ) -> None:
        super().__init__()
        self._options = options
        self._demo = demo
        self._tui_config = tui_config or TuiConfig()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            self._placeholder_text(),
            id="placeholder",
            classes="placeholder",
        )
        yield Footer()

    def on_mount(self) -> None:  # noqa: D401 — Textual hook name
        self._apply_theme()

    def _apply_theme(self) -> None:
        saved = self._tui_config.theme
        active = "monochrome" if os.environ.get("NO_COLOR") else saved
        if active in {"slate", "parchment", "colorblind", "monochrome"}:
            # Real themes register in a later commit; for now we keep
            # Textual's built-in palette so the shell still has colors.
            try:
                self.theme = active if active in self.available_themes else "textual-dark"
            except Exception:
                self.theme = "textual-dark"

    def _placeholder_text(self) -> str:
        scope = "demo data" if self._demo else "real local logs"
        return (
            "Caliper TUI is live.\n\n"
            f"Loaded against: {scope}.\n"
            "Press `q` to quit.\n\n"
            "Home, Sessions, Models, Limits, Live, Forecast, What-If,\n"
            "Budgets, Insights, Doctor, and Receipt land in subsequent commits."
        )

    def action_refresh(self) -> None:
        # Real refresh wiring lands with the worker commit (T06).
        self.notify("Refresh wired in T06 — coming soon.")

    def action_show_help(self) -> None:
        self.notify("Help overlay lands with screens/help.")

    def action_cycle_theme(self) -> None:
        self.notify("Theme cycling lands with T04.")


def run_tui(
    options: RuntimeOptions,
    *,
    demo: bool = False,
    tui_config: TuiConfig | None = None,
) -> None:
    """Boot the Textual app against the given options.

    Caller is expected to have already verified that ``textual`` is
    importable. ``caliper.cli.tui`` is that caller today.
    """
    if tui_config is None:
        tui_config = load_tui_config(load_config(options.config_path))
    CaliperApp(options, demo=demo, tui_config=tui_config).run()


def build_demo_options(template: RuntimeOptions) -> RuntimeOptions:
    """Return a RuntimeOptions copy whose paths point at empty demo dirs.

    Used by ``caliper tui --demo`` and by tests. The actual synthetic
    LoadResult lives in :mod:`caliper.tui.demo` (later commit).
    """
    sandbox = Path(os.environ.get("CALIPER_DEMO_HOME", "")) or template.session_root
    return replace(template, session_root=sandbox)
