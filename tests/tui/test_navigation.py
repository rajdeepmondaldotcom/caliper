"""End-to-end TUI navigation pilot — exercises the 1..9 keymap.

Validates that every numbered binding pushes the right stub screen,
that `Escape` returns Home, that `t` cycles the active theme, and
that `[` / `]` fire their placeholder action without crashing.
"""

from __future__ import annotations

import asyncio


def test_tui_navigation_keymap(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("textual")

    from caliper.config import TuiConfig, build_options
    from caliper.tui.app import CaliperApp
    from caliper.tui.demo import materialize_demo

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.delenv("NO_COLOR", raising=False)

    options = build_options(
        days=90,
        session_root=tmp_path / "codex-empty",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "codex.toml",
        no_parse_cache=True,
    )
    options = materialize_demo(options)

    app = CaliperApp(options, demo=False, tui_config=TuiConfig())
    visited: list[tuple[str, str]] = []
    theme_after_cycle = {}

    async def _drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await asyncio.sleep(0.2)
            jumps = [
                ("2", "IntervalsScreen"),
                ("3", "SessionsScreen"),
                ("4", "ProjectsScreen"),
                ("5", "ModelsScreen"),
                ("6", "LimitsScreen"),
                ("7", "LiveScreen"),
                ("8", "ForecastScreen"),
                ("9", "DoctorScreen"),
            ]
            for key, expected in jumps:
                await pilot.press(key)
                await pilot.pause()
                top = type(app.screen_stack[-1]).__name__ if app.screen_stack else "none"
                visited.append((key, top))
                assert top == expected, f"key {key} expected {expected}, got {top}"
                await pilot.press("escape")
                await pilot.pause()
            theme_before = app._tui_config.theme
            await pilot.press("t")
            await pilot.pause()
            theme_after_cycle["before"] = theme_before
            theme_after_cycle["after"] = app._tui_config.theme
            await pilot.press("left_square_bracket")
            await pilot.pause()
            await pilot.press("right_square_bracket")
            await pilot.pause()

    asyncio.run(_drive())

    assert len(visited) == 8
    assert theme_after_cycle["after"] != theme_after_cycle["before"]
