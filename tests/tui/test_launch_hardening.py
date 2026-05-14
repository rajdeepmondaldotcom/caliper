from __future__ import annotations

import asyncio


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

    assert "Last&#160;7&#160;days" in svg
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
