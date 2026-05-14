"""Caliper Textual application shell — workers, screens, themes wired in."""

from __future__ import annotations

import contextlib
import datetime as dt
import os
from dataclasses import replace
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header
from textual.worker import Worker, get_current_worker

from caliper.config import TuiConfig, load_config, load_tui_config
from caliper.models import RuntimeOptions
from caliper.timeutil import local_timezone
from caliper.tui.demo import materialize_demo
from caliper.tui.messages import (
    LoadCancelled,
    LoadFailed,
    LoadFileCacheHit,
    LoadFileDone,
    LoadFinished,
    LoadStarted,
    LoadSucceeded,
    WorkerCancelled,
)
from caliper.tui.progress import TextualParseProgress
from caliper.tui.screens.budgets import BudgetsScreen
from caliper.tui.screens.doctor import DoctorScreen
from caliper.tui.screens.forecast import ForecastScreen
from caliper.tui.screens.home import HomeScreen
from caliper.tui.screens.insights import InsightsScreen
from caliper.tui.screens.intervals import IntervalsScreen
from caliper.tui.screens.limits import LimitsScreen
from caliper.tui.screens.live import LiveScreen
from caliper.tui.screens.models import ModelsScreen
from caliper.tui.screens.projects import ProjectsScreen
from caliper.tui.screens.receipt import ReceiptScreen
from caliper.tui.screens.sessions import SessionsScreen
from caliper.tui.screens.welcome import WelcomeScreen, welcome_already_seen
from caliper.tui.screens.whatif import WhatIfScreen
from caliper.tui.state import AppSnapshot, default_scope
from caliper.tui.workers import build_overview, run_load


class CaliperApp(App):
    """The Textual app shell.

    Hosts the reactive ``AppSnapshot`` store, dispatches worker
    refreshes, and routes keymaps to the Home screen + numbered jumps.
    """

    CSS_PATH = [
        Path(__file__).parent / "tcss" / "base.tcss",
        Path(__file__).parent / "tcss" / "themes" / "slate.tcss",
    ]
    TITLE = "Caliper"

    BINDINGS = [
        Binding("q", "quit", "quit", priority=True),
        Binding("question_mark", "show_help", "help"),
        Binding("r", "refresh", "refresh"),
        Binding("t", "cycle_theme", "theme"),
        Binding("1", "go('home')", "Home"),
        Binding("2", "go('intervals')", "Daily/Weekly"),
        Binding("3", "go('sessions')", "Sessions"),
        Binding("4", "go('projects')", "Projects"),
        Binding("5", "go('models')", "Models"),
        Binding("6", "go('limits')", "Limits"),
        Binding("7", "go('live')", "Live"),
        Binding("8", "go('forecast')", "Forecast"),
        Binding("9", "go('doctor')", "Doctor"),
        Binding("left_square_bracket", "step_back", "← interval", show=False),
        Binding("right_square_bracket", "step_forward", "interval →", show=False),
    ]

    snapshot: reactive[AppSnapshot] = reactive(None, layout=True)  # type: ignore[assignment]

    _SCREENS = {
        "intervals": IntervalsScreen,
        "sessions": SessionsScreen,
        "projects": ProjectsScreen,
        "models": ModelsScreen,
        "limits": LimitsScreen,
        "live": LiveScreen,
        "forecast": ForecastScreen,
        "whatif": WhatIfScreen,
        "budgets": BudgetsScreen,
        "insights": InsightsScreen,
        "doctor": DoctorScreen,
        "receipt": ReceiptScreen,
    }

    _THEME_ORDER = ("slate", "parchment", "colorblind", "monochrome")

    def __init__(
        self,
        options: RuntimeOptions,
        *,
        demo: bool = False,
        tui_config: TuiConfig | None = None,
    ) -> None:
        super().__init__()
        self._demo = demo
        self._tui_config = tui_config or TuiConfig()
        if demo:
            options = materialize_demo(options)
        self.snapshot = AppSnapshot(
            options=options,
            scope=default_scope(dt.datetime.now(tz=local_timezone())),
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

    def on_mount(self) -> None:
        self._apply_theme()
        self.push_screen(HomeScreen())
        if self._tui_config.show_demo_on_first_run and not welcome_already_seen():
            self.push_screen(WelcomeScreen())
        self.action_refresh()

    # ------------------------------------------------------------------ themes
    def _apply_theme(self) -> None:
        saved = self._tui_config.theme
        active = "monochrome" if os.environ.get("NO_COLOR") else saved
        self._set_theme(active)

    def _set_theme(self, name: str) -> None:
        available = set(getattr(self, "available_themes", {}))
        fallback = {
            "slate": "textual-dark",
            "parchment": "textual-light",
            "colorblind": "nord" if "nord" in available else "textual-dark",
            "monochrome": "textual-ansi",
        }.get(name, "textual-dark")
        target = name if name in available else fallback
        with contextlib.suppress(Exception):
            self.theme = target

    def action_cycle_theme(self) -> None:
        try:
            current_index = self._THEME_ORDER.index(self._tui_config.theme)
        except ValueError:
            current_index = 0
        next_theme = self._THEME_ORDER[(current_index + 1) % len(self._THEME_ORDER)]
        self._tui_config = replace(self._tui_config, theme=next_theme)
        self._set_theme(next_theme)
        self.notify(f"Theme: {next_theme}")

    # ------------------------------------------------------------------ navigation
    def action_go(self, name: str) -> None:
        if name == "home":
            while len(self.screen_stack) > 1:
                self.pop_screen()
            return
        screen_cls = self._SCREENS.get(name)
        if screen_cls is None:
            self.notify(f"Unknown screen: {name}")
            return
        self.push_screen(screen_cls())

    def action_step_back(self) -> None:
        self.notify("Time scrubber lands with T23 — coming soon.", timeout=3)

    def action_step_forward(self) -> None:
        self.notify("Time scrubber lands with T23 — coming soon.", timeout=3)

    def action_show_help(self) -> None:
        self.notify(
            "Keys: q quit · r refresh · t theme · 1–9 jump · ? help",
            timeout=4,
        )

    # ------------------------------------------------------------------ refresh
    def action_refresh(self) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        self.snapshot = replace(
            snapshot,
            refresh_started_at=dt.datetime.now(tz=local_timezone()),
            refresh_completed_at=None,
            refresh_error=None,
            load_total_files=0,
            load_files_done=0,
            load_files_cached=0,
            cancelled=False,
        )
        self.run_worker(
            self._load_worker(),
            thread=True,
            exclusive=True,
            group="data",
            exit_on_error=False,
        )

    def _load_worker(self):
        snapshot = self.snapshot
        progress = TextualParseProgress(self)

        def _body():
            worker = get_current_worker()
            try:
                result, card = run_load(snapshot.options, progress)
                if worker.is_cancelled:
                    self.post_message(LoadCancelled())
                    return
                derived = build_overview(result, snapshot.options, card)
                self.post_message(LoadSucceeded(result, card))
                # Hand the derived aggregates over through the same reactive.
                self.call_from_thread(self._apply_derived, derived)
            except WorkerCancelled:
                self.post_message(LoadCancelled())
            except Exception as exc:  # pragma: no cover - surfaced to UI
                self.post_message(LoadFailed(exc))

        return _body

    def _apply_derived(self, derived: dict) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        self.snapshot = replace(
            snapshot,
            overview_windows=derived["overview_windows"],
            overview_total=derived["overview_total"],
            daily=derived["daily"],
            weekly=derived["weekly"],
            monthly=derived["monthly"],
            sessions=derived["sessions"],
            projects=derived["projects"],
            models=derived["models"],
            insights=derived["insights"],
            primary_window=derived["primary_window"],
            secondary_window=derived["secondary_window"],
            refresh_completed_at=dt.datetime.now(tz=local_timezone()),
        )

    # ------------------------------------------------------------------ messages
    def on_load_started(self, event: LoadStarted) -> None:
        self.snapshot = replace(self.snapshot, load_total_files=event.total)

    def on_load_file_done(self, event: LoadFileDone) -> None:
        snap = self.snapshot
        self.snapshot = replace(snap, load_files_done=snap.load_files_done + 1)

    def on_load_file_cache_hit(self, event: LoadFileCacheHit) -> None:
        snap = self.snapshot
        self.snapshot = replace(snap, load_files_cached=snap.load_files_cached + 1)

    def on_load_finished(self, event: LoadFinished) -> None:
        pass  # actual completion happens in _apply_derived

    def on_load_succeeded(self, event: LoadSucceeded) -> None:
        snap = self.snapshot
        self.snapshot = replace(snap, load_result=event.result, rate_card=event.rate_card)

    def on_load_failed(self, event: LoadFailed) -> None:
        snap = self.snapshot
        self.snapshot = replace(
            snap,
            refresh_completed_at=dt.datetime.now(tz=local_timezone()),
            refresh_error=str(event.error),
        )

    def on_load_cancelled(self, event: LoadCancelled) -> None:
        snap = self.snapshot
        self.snapshot = replace(snap, cancelled=True, refresh_completed_at=None)

    # ------------------------------------------------------------------ reactive
    def watch_snapshot(self, snapshot: AppSnapshot) -> None:
        if snapshot is None:
            return
        # Forward to the active HomeScreen if visible.
        if self.screen_stack:
            top = self.screen_stack[-1]
            if isinstance(top, HomeScreen):
                top.update_from_snapshot(snapshot)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:  # noqa: D401
        # Hook for future logging / status pill; intentionally quiet today.
        return None


def run_tui(
    options: RuntimeOptions,
    *,
    demo: bool = False,
    tui_config: TuiConfig | None = None,
) -> None:
    if tui_config is None:
        tui_config = load_tui_config(load_config(options.config_path))
    CaliperApp(options, demo=demo, tui_config=tui_config).run()


def build_demo_options(template: RuntimeOptions) -> RuntimeOptions:
    """Back-compat shim — :func:`materialize_demo` is the canonical path."""
    return materialize_demo(template)
