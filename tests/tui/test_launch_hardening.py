from __future__ import annotations

import asyncio


def _demo_app(tmp_path, monkeypatch, *, demo=True, first_run=False, no_color=False, size_days=90):
    import pytest

    pytest.importorskip("textual")

    from caliper.config import TuiConfig, build_options
    from caliper.tui.app import CaliperApp

    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")

    options = build_options(
        days=size_days,
        session_root=tmp_path / "codex-empty",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "codex.toml",
        no_parse_cache=True,
    )
    return CaliperApp(
        options,
        demo=demo,
        tui_config=TuiConfig(show_demo_on_first_run=first_run, no_watchdog=True, theme="slate"),
    )


async def _wait_for_first_load(app, pilot) -> None:
    for _ in range(80):
        await pilot.pause(0.05)
        if app.snapshot.refresh_completed_at:
            break
    await pilot.pause(0.2)


def _assert_no_obvious_midword_splits(svg: str) -> None:
    for fragment in (
        "pa\nlette",
        "Pro\nject",
        "Mo\ndel",
        "Sta\ntus",
        "De\ntail",
        "Fore\ncast",
        "Doc\ntor",
        "Lim\nits",
        "re\nfresh",
        "in\nsights",
    ):
        assert fragment not in svg


def test_demo_home_renders_body_and_no_wrapped_default_footer(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("textual")

    from caliper.config import TuiConfig, build_options
    from caliper.tui.app import CaliperApp

    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        days=90,
        session_root=tmp_path / "codex-empty",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "codex.toml",
        no_parse_cache=True,
    )

    app = CaliperApp(
        options,
        demo=True,
        tui_config=TuiConfig(show_demo_on_first_run=False, no_watchdog=True),
    )

    async def _drive() -> str:
        async with app.run_test(size=(80, 24)) as pilot:
            for _ in range(80):
                await pilot.pause(0.05)
                if app.snapshot.refresh_completed_at:
                    break
            await pilot.pause(0.2)
            return app.export_screenshot()

    svg = asyncio.run(_drive())

    assert "7d" in svg
    assert "OpenAI" in svg
    assert "pa\nlette" not in svg
    assert "pa lette" not in svg


def test_demo_projects_and_models_keep_primary_labels_visible(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("textual")

    from caliper.config import TuiConfig, build_options
    from caliper.tui.app import CaliperApp

    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        days=90,
        session_root=tmp_path / "codex-empty",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "codex.toml",
        no_parse_cache=True,
    )
    app = CaliperApp(
        options,
        demo=True,
        tui_config=TuiConfig(show_demo_on_first_run=False, no_watchdog=True),
    )

    async def _drive() -> tuple[str, str]:
        async with app.run_test(size=(80, 24)) as pilot:
            for _ in range(80):
                await pilot.pause(0.05)
                if app.snapshot.refresh_completed_at:
                    break
            await pilot.press("4")
            await pilot.pause(0.2)
            projects = app.export_screenshot()
            await pilot.press("escape")
            await pilot.pause(0.1)
            await pilot.press("5")
            await pilot.pause(0.2)
            models = app.export_screenshot()
            return projects, models

    projects, models = asyncio.run(_drive())

    assert "Project" in projects
    assert "caliper-ai" in projects
    assert "Model" in models
    assert "gpt-5.5" in models


def test_demo_mode_skips_first_run_welcome(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("textual")

    from caliper.config import TuiConfig, build_options
    from caliper.tui.app import CaliperApp

    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    options = build_options(
        days=90,
        session_root=tmp_path / "codex-empty",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "codex.toml",
        no_parse_cache=True,
    )
    app = CaliperApp(
        options,
        demo=True,
        tui_config=TuiConfig(show_demo_on_first_run=True, no_watchdog=True),
    )

    async def _drive() -> str:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.2)
            return app.export_screenshot()

    svg = asyncio.run(_drive())

    assert "Press&#160;space&#160;to&#160;enter" not in svg
    assert "Caliper" in svg


def test_no_color_selects_monochrome_theme(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("textual")

    from caliper.config import TuiConfig, build_options
    from caliper.tui.app import CaliperApp

    monkeypatch.setenv("NO_COLOR", "1")
    options = build_options(
        days=1,
        session_root=tmp_path / "codex-empty",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "codex.toml",
        no_parse_cache=True,
    )
    app = CaliperApp(
        options,
        demo=True,
        tui_config=TuiConfig(show_demo_on_first_run=False, no_watchdog=True, theme="slate"),
    )

    async def _drive() -> str:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.2)
            return app.theme

    assert asyncio.run(_drive()) == "monochrome"


def test_shortcut_navigation_reaches_secondary_screens(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("textual")

    from caliper.config import TuiConfig, build_options
    from caliper.tui.app import CaliperApp

    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        days=90,
        session_root=tmp_path / "codex-empty",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "codex.toml",
        no_parse_cache=True,
    )
    app = CaliperApp(
        options,
        demo=True,
        tui_config=TuiConfig(show_demo_on_first_run=False, no_watchdog=True),
    )

    async def _drive() -> list[str]:
        titles: list[str] = []
        async with app.run_test(size=(80, 24)) as pilot:
            for key in ("0", "escape", "w", "escape", "b", "escape", "i", "escape", "?"):
                await pilot.press(key)
                await pilot.pause(0.1)
                if key != "escape":
                    titles.append(type(app.screen).__name__)
            return titles

    assert asyncio.run(_drive()) == [
        "ReceiptScreen",
        "WhatIfScreen",
        "BudgetsScreen",
        "InsightsScreen",
        "HelpScreen",
    ]


def test_doctor_redacts_local_paths_by_default(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("textual")

    from caliper.config import TuiConfig, build_options
    from caliper.tui.app import CaliperApp

    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        days=90,
        session_root=tmp_path / "codex-empty",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "codex.toml",
        no_parse_cache=True,
    )
    app = CaliperApp(
        options,
        demo=True,
        tui_config=TuiConfig(show_demo_on_first_run=False, no_watchdog=True),
    )

    async def _drive() -> str:
        async with app.run_test(size=(80, 24)) as pilot:
            await _wait_for_first_load(app, pilot)
            await pilot.press("9")
            await pilot.pause(0.2)
            redacted = app.export_screenshot()
            await pilot.press("p")
            await _wait_for_first_load(app, pilot)
            await pilot.pause(0.2)
            revealed = app.export_screenshot()
            return redacted, revealed, app.snapshot.options.show_paths

    redacted, revealed, show_paths = asyncio.run(_drive())

    assert "Local&#160;paths&#160;redacted" in redacted
    assert str(tmp_path) not in redacted
    assert "Local&#160;paths&#160;visible" in revealed
    assert show_paths is True


def test_doctor_redacted_detail_uses_basename_only() -> None:
    from caliper.tui.screens.doctor import _redact_path_detail

    assert _redact_path_detail("/tmp/private/codex-empty (0 JSONL files)") == (
        "codex-empty (0 JSONL files)"
    )


def test_tui_screenshot_regression_matrix_80x24(tmp_path, monkeypatch):
    app = _demo_app(tmp_path, monkeypatch)

    async def _drive() -> dict[str, str]:
        async with app.run_test(size=(80, 24)) as pilot:
            await _wait_for_first_load(app, pilot)
            shots = {"home": app.export_screenshot()}
            for name, key in (("doctor", "9"), ("models", "5"), ("projects", "4"), ("limits", "6")):
                await pilot.press(key)
                await pilot.pause(0.2)
                shots[name] = app.export_screenshot()
                await pilot.press("escape")
                await pilot.pause(0.1)
            return shots

    shots = asyncio.run(_drive())

    assert "7d" in shots["home"]
    assert "Doctor" in shots["doctor"]
    assert "Model" in shots["models"]
    assert "Projects" in shots["projects"]
    assert "Limits" in shots["limits"]
    for svg in shots.values():
        _assert_no_obvious_midword_splits(svg)
    assert str(tmp_path) not in shots["doctor"]


def test_tui_screenshot_regression_matrix_120x40(tmp_path, monkeypatch):
    app = _demo_app(tmp_path, monkeypatch)

    async def _drive() -> dict[str, str]:
        async with app.run_test(size=(120, 40)) as pilot:
            await _wait_for_first_load(app, pilot)
            shots = {"home": app.export_screenshot()}
            for name, key in (("sessions", "3"), ("projects", "4"), ("forecast", "8")):
                await pilot.press(key)
                await pilot.pause(0.2)
                shots[name] = app.export_screenshot()
                await pilot.press("escape")
                await pilot.pause(0.1)
            return shots

    shots = asyncio.run(_drive())

    assert "Recent&#160;sessions" in shots["home"]
    assert "sessions" in shots["sessions"]
    assert "Projects" in shots["projects"]
    assert "Forecast" in shots["forecast"]
    for svg in shots.values():
        _assert_no_obvious_midword_splits(svg)


def test_no_color_screenshot_regression(tmp_path, monkeypatch):
    app = _demo_app(tmp_path, monkeypatch, no_color=True)

    async def _drive() -> tuple[str, str]:
        async with app.run_test(size=(80, 24)) as pilot:
            await _wait_for_first_load(app, pilot)
            return app.theme, app.export_screenshot()

    theme, svg = asyncio.run(_drive())

    assert theme == "monochrome"
    assert "Caliper" in svg
    _assert_no_obvious_midword_splits(svg)


def test_first_run_welcome_screenshot_regression(tmp_path, monkeypatch):
    app = _demo_app(tmp_path, monkeypatch, demo=False, first_run=True)

    async def _drive() -> str:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.2)
            return app.export_screenshot()

    svg = asyncio.run(_drive())

    assert "Local&#160;AI&#160;cost&#160;ledger" in svg
    assert "Press&#160;space&#160;to&#160;enter" in svg
    _assert_no_obvious_midword_splits(svg)
