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
            is_screen = (
                isinstance(obj, type)
                and issubclass(obj, CaliperScreen)
                and obj is not CaliperScreen
            )
            if is_screen:
                assert obj.SCREEN_TITLE, f"{obj.__name__} missing SCREEN_TITLE"
                assert obj.SCREEN_QUESTION, f"{obj.__name__} missing SCREEN_QUESTION"


def test_palette_provider_loads():
    from caliper.tui.palette import CaliperCommands

    cmds = CaliperCommands.app_actions.fget(CaliperCommands.__new__(CaliperCommands))  # type: ignore[attr-defined]
    actions = {name: key for name, key, _help in cmds}
    assert actions["Go to Home"] == "1"
    assert actions["Go to Receipt"] == "0"
    assert actions["Go to What-If"] == "w"
    assert actions["Go to Budgets"] == "b"
    assert actions["Go to Insights"] == "i"
    assert actions["Go to Help"] == "question_mark"
    assert actions["Cycle theme"] == "t"
    assert actions["Refresh"] == "r"


def test_palette_provider_discovers_and_searches_new_screen_actions():
    import asyncio

    from caliper.tui.palette import CaliperCommands

    class FakeApp:
        def __init__(self) -> None:
            self.keys: list[str] = []

        async def simulate_key(self, key: str) -> None:
            self.keys.append(key)

    class FakeScreen:
        focused = None

        def __init__(self) -> None:
            self.app = FakeApp()

    async def _collect():
        provider = CaliperCommands(FakeScreen())  # type: ignore[arg-type]
        discovered = [hit async for hit in provider.discover()]
        searched = [hit async for hit in provider.search("receipt")]
        await discovered[0].command()
        return provider.screen.app.keys, discovered, searched

    keys, discovered, searched = asyncio.run(_collect())

    assert keys == ["1"]
    assert {hit.text for hit in discovered} >= {"Go to Receipt", "Go to What-If", "Go to Help"}
    assert [hit.text for hit in searched] == ["Go to Receipt"]


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


def test_tui_screens_do_not_expose_placeholder_copy():
    from pathlib import Path

    base = Path(__file__).parent.parent.parent / "src" / "caliper" / "tui" / "screens"
    forbidden = (
        "coming soon",
        "follow-up",
        "lands in",
        "lands with",
        "This screen lands",
        "enter drill",
    )
    for path in base.glob("*.py"):
        text = path.read_text()
        for phrase in forbidden:
            assert phrase not in text, f"{path.name} still exposes {phrase!r}"
