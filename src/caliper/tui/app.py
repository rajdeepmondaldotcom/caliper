"""Caliper Textual application shell — workers, screens, themes wired in."""

from __future__ import annotations

import contextlib
import datetime as dt
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.theme import Theme
from textual.worker import Worker, get_current_worker

from caliper.config import TuiConfig, load_config, load_tui_config
from caliper.intervals import Interval
from caliper.models import RuntimeOptions
from caliper.timeutil import local_timezone
from caliper.tui.demo import materialize_demo
from caliper.tui.manifest import TuiLoadManifest, build_load_manifest
from caliper.tui.messages import (
    LoadCancelled,
    LoadFailed,
    LoadFinished,
    LoadProgress,
    LoadStarted,
    LoadSucceeded,
    WorkerCancelled,
)
from caliper.tui.progress import TextualParseProgress
from caliper.tui.screens.budgets import BudgetsScreen
from caliper.tui.screens.doctor import DoctorScreen
from caliper.tui.screens.forecast import ForecastScreen
from caliper.tui.screens.help import HelpScreen
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
from caliper.tui.state import AppSnapshot, apply_scope, default_scope
from caliper.tui.widgets.loading_overlay import LoadingOverlay
from caliper.tui.workers import build_overview, run_load


class CaliperApp(App):
    """The Textual app shell.

    Hosts the reactive ``AppSnapshot`` store, dispatches worker
    refreshes, and routes keymaps to the Home screen + numbered jumps.
    """

    CSS_PATH = [
        Path(__file__).parent / "tcss" / "base.tcss",
    ]
    TITLE = "Caliper"

    BINDINGS = [
        Binding("q", "quit", "quit", priority=True),
        Binding("question_mark", "show_help", "help", priority=True),
        Binding("r", "refresh", "refresh", priority=True),
        Binding("t", "cycle_theme", "theme", priority=True),
        Binding("p", "toggle_redact", "redact", show=False, priority=True),
        Binding("1", "go('home')", "Home", priority=True),
        Binding("2", "go('intervals')", "Daily/Weekly", priority=True),
        Binding("3", "go('sessions')", "Sessions", priority=True),
        Binding("4", "go('projects')", "Projects", priority=True),
        Binding("5", "go('models')", "Models", priority=True),
        Binding("6", "go('limits')", "Limits", priority=True),
        Binding("7", "go('live')", "Live", priority=True),
        Binding("8", "go('forecast')", "Forecast", priority=True),
        Binding("9", "go('doctor')", "Doctor", priority=True),
        Binding("0", "go('receipt')", "Receipt", priority=True),
        Binding("w", "go('whatif')", "What-If", priority=True),
        Binding("b", "go('budgets')", "Budgets", priority=True),
        Binding("i", "go('insights')", "Insights", priority=True),
        Binding("left_square_bracket", "step_back", "< interval", show=False, priority=True),
        Binding("right_square_bracket", "step_forward", "interval >", show=False, priority=True),
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
        "help": HelpScreen,
    }

    _GLOBAL_NAV_KEYS = {
        "1": "home",
        "2": "intervals",
        "3": "sessions",
        "4": "projects",
        "5": "models",
        "6": "limits",
        "7": "live",
        "8": "forecast",
        "9": "doctor",
        "0": "receipt",
        "w": "whatif",
        "b": "budgets",
        "i": "insights",
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
        self._load_generation = 0
        self._last_manifest: TuiLoadManifest | None = None
        self._last_load_result = None
        self._last_rate_card = None
        self._last_derived: dict[str, Any] | None = None
        self._watch_observer = None
        self._refresh_timer = None
        self._poll_timer = None
        self._progress_total = 0
        self._progress_done = 0
        self._progress_cached = 0
        self._progress_stage = "idle"

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self._register_caliper_themes()
        self._apply_theme()
        self.push_screen(HomeScreen())
        if (
            not self._demo
            and self._tui_config.show_demo_on_first_run
            and not welcome_already_seen()
        ):
            self.push_screen(WelcomeScreen())
        self.action_refresh()
        self._start_refresh_monitoring()

    def on_unmount(self) -> None:
        self._stop_refresh_monitoring()

    def on_key(self, event) -> None:
        key = event.key
        if key in self._GLOBAL_NAV_KEYS:
            event.prevent_default()
            event.stop()
            self.action_go(self._GLOBAL_NAV_KEYS[key])
            return
        if key == "question_mark":
            event.prevent_default()
            event.stop()
            self.action_show_help()
            return
        if key == "r":
            event.prevent_default()
            event.stop()
            self.action_refresh()
            return
        if key == "t":
            event.prevent_default()
            event.stop()
            self.action_cycle_theme()
            return
        if key == "p":
            event.prevent_default()
            event.stop()
            self.action_toggle_redact()
            return
        if key in {"left_square_bracket", "["}:
            event.prevent_default()
            event.stop()
            self.action_step_back()
            return
        if key in {"right_square_bracket", "]"}:
            event.prevent_default()
            event.stop()
            self.action_step_forward()

    # ------------------------------------------------------------------ themes
    def _register_caliper_themes(self) -> None:
        themes = (
            Theme(
                name="slate",
                primary="#7f8dbd",
                secondary="#8fb3a8",
                warning="#d0a85c",
                error="#d56a6a",
                success="#7fbf8f",
                accent="#c7a86a",
                foreground="#d6dae3",
                background="#11151b",
                surface="#151a22",
                panel="#1c2230",
                dark=True,
            ),
            Theme(
                name="parchment",
                primary="#4d6f85",
                secondary="#7a6f46",
                warning="#a66824",
                error="#a74845",
                success="#497a57",
                accent="#8f5f3b",
                foreground="#1f2933",
                background="#f7f2e8",
                surface="#fbf7ef",
                panel="#ece3d4",
                dark=False,
            ),
            Theme(
                name="colorblind",
                primary="#0072b2",
                secondary="#009e73",
                warning="#e69f00",
                error="#d55e00",
                success="#009e73",
                accent="#56b4e9",
                foreground="#f2f2f2",
                background="#101418",
                surface="#151b20",
                panel="#202830",
                dark=True,
            ),
            Theme(
                name="monochrome",
                primary="#d0d0d0",
                secondary="#a8a8a8",
                warning="#e0e0e0",
                error="#ffffff",
                success="#d0d0d0",
                accent="#ffffff",
                foreground="#d0d0d0",
                background="#000000",
                surface="#000000",
                panel="#101010",
                dark=True,
                ansi=True,
                variables={
                    "ansi-background": "ansi_black",
                    "ansi-foreground": "ansi_white",
                    "border-blurred": "ansi_black",
                    "block-cursor-foreground": "ansi_black",
                    "block-cursor-background": "ansi_white",
                    "input-cursor-background": "ansi_black",
                    "input-cursor-foreground": "ansi_bright_white",
                    "input-cursor-text-style": "none",
                    "input-selection-background": "ansi_bright_blue",
                    "input-selection-foreground": "ansi_black",
                    "screen-selection-background": "ansi_bright_blue",
                    "screen-selection-foreground": "ansi_black",
                },
            ),
        )
        for theme in themes:
            with contextlib.suppress(Exception):
                self.register_theme(theme)

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
            "monochrome": "ansi-dark" if "ansi-dark" in available else "textual-dark",
        }.get(name, "textual-dark")
        target = name if name in available else fallback
        with contextlib.suppress(Exception):
            self.theme = target

    def action_cycle_theme(self) -> None:
        if os.environ.get("NO_COLOR"):
            self._set_theme("monochrome")
            self.notify("Theme: monochrome (NO_COLOR)")
            return
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
            self._show_home()
            return
        screen_cls = self._SCREENS.get(name)
        if screen_cls is None:
            self.notify(f"Unknown screen: {name}")
            return
        self._show_home()
        self.push_screen(screen_cls())

    def _show_home(self) -> None:
        while self.screen_stack and not isinstance(self.screen_stack[-1], HomeScreen):
            self.pop_screen()
        if not self.screen_stack or not isinstance(self.screen_stack[-1], HomeScreen):
            self.push_screen(HomeScreen())

    def action_step_back(self) -> None:
        self._step_interval(-1)

    def action_step_forward(self) -> None:
        self._step_interval(1)

    def _step_interval(self, direction: int) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        current = snapshot.scope.interval
        span = current.end - current.start
        start = current.start + span * direction
        end = current.end + span * direction
        label = f"{start:%Y-%m-%d} to {end:%Y-%m-%d}"
        self.snapshot = apply_scope(
            snapshot,
            interval=Interval(start=start, end=end, label=label),
        )
        self.action_refresh()

    def action_toggle_redact(self) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        show_prompts = not snapshot.options.show_prompts
        self.snapshot = apply_scope(
            snapshot,
            show_prompts=show_prompts,
            show_paths=show_prompts,
        )
        self.notify(
            "Sensitive labels and paths shown"
            if show_prompts
            else "Sensitive labels and paths redacted"
        )
        self.action_refresh()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    # ------------------------------------------------------------------ refresh
    def action_refresh(self) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        self._load_generation += 1
        generation = self._load_generation
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
        self._set_overlay_progress(
            total=0,
            done=0,
            cached=0,
            stage="discovering",
        )
        self.run_worker(
            self._load_worker(
                generation=generation,
                snapshot=self.snapshot,
                previous_manifest=self._last_manifest,
                previous_result=self._last_load_result,
                previous_card=self._last_rate_card,
                previous_derived=self._last_derived,
            ),
            thread=True,
            exclusive=True,
            group="data",
            exit_on_error=False,
        )

    def _load_worker(
        self,
        *,
        generation: int,
        snapshot: AppSnapshot,
        previous_manifest: TuiLoadManifest | None,
        previous_result,
        previous_card,
        previous_derived: dict[str, Any] | None,
    ):
        progress = TextualParseProgress(self, generation=generation)

        def _body():
            worker = get_current_worker()
            try:
                manifest = build_load_manifest(snapshot.options)
                if worker.is_cancelled:
                    self.post_message(LoadCancelled(generation=generation))
                    return
                if (
                    manifest == previous_manifest
                    and previous_result is not None
                    and previous_card is not None
                    and previous_derived is not None
                ):
                    progress.reused(len(manifest.files))
                    self.post_message(
                        LoadSucceeded(
                            previous_result,
                            previous_card,
                            previous_derived,
                            manifest,
                            reused=True,
                            generation=generation,
                        )
                    )
                    return
                result, card = run_load(snapshot.options, progress)
                if worker.is_cancelled:
                    self.post_message(LoadCancelled(generation=generation))
                    return
                progress.aggregating()
                derived = build_overview(result, snapshot.options, card)
                self.post_message(
                    LoadSucceeded(
                        result,
                        card,
                        derived,
                        manifest,
                        generation=generation,
                    )
                )
            except WorkerCancelled:
                self.post_message(LoadCancelled(generation=generation))
            except Exception as exc:  # pragma: no cover - surfaced to UI
                self.post_message(LoadFailed(exc, generation=generation))

        return _body

    # ------------------------------------------------------------------ messages
    def on_load_started(self, event: LoadStarted) -> None:
        if not self._is_current(event):
            return
        self._set_overlay_progress(
            total=event.total,
            done=self._progress_done,
            cached=self._progress_cached,
            stage="reading",
        )

    def on_load_progress(self, event: LoadProgress) -> None:
        if not self._is_current(event):
            return
        self._set_overlay_progress(
            total=event.total,
            done=event.done,
            cached=event.cached,
            stage=event.stage,
        )

    def on_load_finished(self, event: LoadFinished) -> None:
        if not self._is_current(event):
            return
        self._set_overlay_progress(
            total=self._progress_total,
            done=self._progress_done,
            cached=self._progress_cached,
            stage="aggregating",
        )

    def on_load_succeeded(self, event: LoadSucceeded) -> None:
        if not self._is_current(event):
            return
        snap = self.snapshot
        derived = event.derived
        self._last_manifest = event.manifest
        self._last_load_result = event.result
        self._last_rate_card = event.rate_card
        self._last_derived = derived
        self.snapshot = replace(
            snap,
            load_result=event.result,
            rate_card=event.rate_card,
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
            refresh_error=None,
            load_total_files=self._progress_total,
            load_files_done=self._progress_done,
            load_files_cached=self._progress_cached,
        )
        self._progress_stage = "done"
        self._hide_loading_overlay()

    def on_load_failed(self, event: LoadFailed) -> None:
        if not self._is_current(event):
            return
        snap = self.snapshot
        self.snapshot = replace(
            snap,
            refresh_completed_at=dt.datetime.now(tz=local_timezone()),
            refresh_error=str(event.error),
        )
        self._hide_loading_overlay()

    def on_load_cancelled(self, event: LoadCancelled) -> None:
        if not self._is_current(event):
            return
        snap = self.snapshot
        self.snapshot = replace(snap, cancelled=True, refresh_completed_at=None)
        self._hide_loading_overlay()

    # ------------------------------------------------------------------ reactive
    def watch_snapshot(self, snapshot: AppSnapshot) -> None:
        if snapshot is None:
            return
        if self.screen_stack:
            top = self.screen_stack[-1]
            update = getattr(top, "update_from_snapshot", None)
            if callable(update):
                update(snapshot)

    # ------------------------------------------------------------------ loading overlay
    def _is_current(self, event) -> bool:
        return getattr(event, "generation", self._load_generation) == self._load_generation

    def _set_overlay_progress(self, *, total: int, done: int, cached: int, stage: str) -> None:
        self._progress_total = total
        self._progress_done = done
        self._progress_cached = cached
        self._progress_stage = stage
        overlay = self._ensure_loading_overlay()
        if overlay is None:
            return
        with contextlib.suppress(NoMatches):
            overlay.update_progress(total=total, done=done, cached=cached, stage=stage)

    def _ensure_loading_overlay(self) -> LoadingOverlay | None:
        if not self.screen_stack:
            return None
        parent = self.screen_stack[-1]
        with contextlib.suppress(NoMatches):
            return parent.query_one("#loading-overlay", LoadingOverlay)
        overlay = LoadingOverlay(id="loading-overlay")
        parent.mount(overlay)
        return overlay

    def _hide_loading_overlay(self) -> None:
        for overlay in list(self.query(LoadingOverlay)):
            overlay.remove()

    # ------------------------------------------------------------------ refresh monitoring
    def _start_refresh_monitoring(self) -> None:
        if self._tui_config.no_watchdog:
            self._poll_timer = self.set_interval(30.0, self._refresh_if_manifest_changed)
            return
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except Exception:
            self._poll_timer = self.set_interval(30.0, self._refresh_if_manifest_changed)
            return

        app = self

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event) -> None:  # noqa: ANN001
                if getattr(event, "is_directory", False):
                    return
                app.call_from_thread(app._schedule_debounced_refresh)

        observer = Observer()
        roots = _watch_roots(self.snapshot.options) if self.snapshot is not None else []
        for root in roots:
            with contextlib.suppress(Exception):
                observer.schedule(_Handler(), str(root), recursive=True)
        if not getattr(observer, "emitters", None):
            self._poll_timer = self.set_interval(30.0, self._refresh_if_manifest_changed)
            return
        observer.start()
        self._watch_observer = observer

    def _stop_refresh_monitoring(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        observer = self._watch_observer
        if observer is not None:
            observer.stop()
            observer.join(timeout=1)
            self._watch_observer = None

    def _schedule_debounced_refresh(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
        self._refresh_timer = self.set_timer(0.75, self._refresh_if_manifest_changed)

    def _refresh_if_manifest_changed(self) -> None:
        snapshot = self.snapshot
        if snapshot is None or snapshot.is_loading():
            return
        try:
            manifest = build_load_manifest(snapshot.options)
        except Exception:
            return
        if manifest != self._last_manifest:
            self.action_refresh()

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


def _watch_roots(options: RuntimeOptions) -> list[Path]:
    roots = {options.session_root}
    claude_override = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if claude_override:
        for item in claude_override.split(os.pathsep):
            for part in item.split(","):
                if part.strip():
                    roots.add(Path(part).expanduser() / "projects")
    else:
        roots.add(Path.home() / ".claude" / "projects")
        xdg = os.environ.get("XDG_CONFIG_HOME")
        roots.add((Path(xdg).expanduser() if xdg else Path.home() / ".config") / "claude")
    cursor_override = os.environ.get("CALIPER_CURSOR_HOME", "").strip()
    if cursor_override:
        roots.add(Path(cursor_override).expanduser())
    else:
        with contextlib.suppress(Exception):
            from platformdirs import user_data_dir

            roots.add(Path(user_data_dir("Cursor")).expanduser())
        roots.add(Path.home() / ".cursor")
    aider_root = Path(os.environ.get("CALIPER_AIDER_ROOT", ".")).expanduser()
    roots.add(aider_root)
    return sorted(root for root in roots if root.exists())
