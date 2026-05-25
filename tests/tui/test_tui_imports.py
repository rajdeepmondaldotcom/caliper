"""Sanity tests that the TUI package imports and exposes its public surface.

The full pilot snapshot suite arrives in T25; these tests guard against
import-time regressions while individual screens are still landing.
"""

from __future__ import annotations

import importlib


def test_caliper_tui_package_imports():
    pkg = importlib.import_module("caliper.tui")
    assert hasattr(pkg, "run_tui")
    assert hasattr(pkg, "CaliperApp")


def test_caliper_tui_state_module():
    state = importlib.import_module("caliper.tui.state")
    assert hasattr(state, "AppSnapshot")
    assert hasattr(state, "Scope")
    assert hasattr(state, "apply_scope")
    assert hasattr(state, "default_scope")


def test_caliper_tui_messages_expose_required_types():
    messages = importlib.import_module("caliper.tui.messages")
    for name in (
        "LoadStarted",
        "LoadFileDone",
        "LoadFileCacheHit",
        "LoadFinished",
        "LoadSucceeded",
        "LoadFailed",
        "LoadCancelled",
        "WorkerCancelled",
    ):
        assert hasattr(messages, name), name


def test_caliper_tui_widgets_import():
    for name in ("sparkline", "cost_card", "window_panel", "loading_overlay"):
        importlib.import_module(f"caliper.tui.widgets.{name}")


def test_caliper_tui_screens_import():
    importlib.import_module("caliper.tui.screens.home")
    importlib.import_module("caliper.tui.screens.stub")


def test_apply_scope_returns_new_snapshot_and_clears_cache():
    import datetime as dt

    from caliper.config import build_options
    from caliper.intervals import Interval
    from caliper.tui.state import AppSnapshot, apply_scope, default_scope

    options = build_options(days=1)
    now = dt.datetime.now(tz=dt.UTC)
    scope = default_scope(now)
    snap = AppSnapshot(options=options, scope=scope, daily=("x",))  # type: ignore[arg-type]
    new_interval = Interval(
        start=now - dt.timedelta(days=30),
        end=now,
        label="Last 30 days",
    )
    new = apply_scope(snap, interval=new_interval, project="repo")
    assert new is not snap
    assert new.options.project == "repo"
    assert new.scope.interval.label == "Last 30 days"
    assert new.daily == ()  # cache cleared


def test_cancelled_snapshot_is_not_loading():
    import datetime as dt

    from caliper.config import build_options
    from caliper.tui.state import AppSnapshot, default_scope

    now = dt.datetime.now(tz=dt.UTC)
    snap = AppSnapshot(
        options=build_options(days=1),
        scope=default_scope(now),
        refresh_started_at=now,
        cancelled=True,
    )

    assert snap.is_loading() is False
