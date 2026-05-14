"""Import-level smoke tests for every real Caliper TUI screen.

Runtime Screen instantiation needs an active App. These tests confirm
that every screen module imports, exposes a Screen subclass, declares
the three-band SCREEN_TITLE / SCREEN_QUESTION, and routes through
CaliperScreen so the layout invariant cannot regress.
"""

from __future__ import annotations

import importlib

from caliper.tui.screens._base import CaliperScreen

SCREEN_MODULES = (
    "caliper.tui.screens.intervals",
    "caliper.tui.screens.projects",
    "caliper.tui.screens.models",
    "caliper.tui.screens.limits",
    "caliper.tui.screens.live",
    "caliper.tui.screens.forecast",
    "caliper.tui.screens.whatif",
    "caliper.tui.screens.budgets",
    "caliper.tui.screens.insights",
    "caliper.tui.screens.doctor",
    "caliper.tui.screens.receipt",
    "caliper.tui.screens.welcome",
    "caliper.tui.screens.sessions",
)


def test_every_screen_module_imports():
    for name in SCREEN_MODULES:
        importlib.import_module(name)


def test_every_screen_subclasses_caliper_screen():
    for name in SCREEN_MODULES:
        mod = importlib.import_module(name)
        screen_classes = [
            obj
            for obj in vars(mod).values()
            if isinstance(obj, type) and issubclass(obj, CaliperScreen) and obj is not CaliperScreen
        ]
        assert screen_classes, f"{name} has no CaliperScreen subclass"


def test_every_screen_declares_title_and_question():
    for name in SCREEN_MODULES:
        mod = importlib.import_module(name)
        for obj in vars(mod).values():
            if isinstance(obj, type) and issubclass(obj, CaliperScreen) and obj is not CaliperScreen:
                assert obj.SCREEN_TITLE, f"{obj.__name__} missing SCREEN_TITLE"
                assert obj.SCREEN_QUESTION, f"{obj.__name__} missing SCREEN_QUESTION"


def test_palette_provider_loads():
    from caliper.tui.palette import CaliperCommands

    cmds = CaliperCommands.app_actions.fget(CaliperCommands.__new__(CaliperCommands))  # type: ignore[attr-defined]
    names = [name for name, _key, _help in cmds]
    assert "Go to Home" in names
    assert "Cycle theme" in names
    assert "Refresh" in names


def test_welcome_state_helpers_round_trip(tmp_path, monkeypatch):
    from caliper.tui.screens import welcome

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert welcome.welcome_already_seen() is False
    welcome.mark_welcome_seen()
    assert welcome.welcome_already_seen() is True


def test_theme_files_exist_on_disk():
    from pathlib import Path

    base = Path(__file__).parent.parent.parent / "src" / "caliper" / "tui" / "tcss" / "themes"
    for name in ("slate.tcss", "parchment.tcss", "colorblind.tcss", "monochrome.tcss"):
        assert (base / name).exists(), f"missing theme file: {name}"
