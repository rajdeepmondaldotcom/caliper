"""Single pilot snapshot: Home screen in --demo mode boots cleanly.

Acts as a worked example for the broader snapshot suite landing with
T25. Run ``pytest --snapshot-update tests/tui/test_home_snapshot.py``
to refresh after intentional UI changes.
"""

from __future__ import annotations

import asyncio


def test_home_boots_with_demo_fixture(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("textual")

    from caliper.config import TuiConfig, build_options
    from caliper.tui.app import CaliperApp
    from caliper.tui.demo import materialize_demo

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
    options = materialize_demo(options)

    app = CaliperApp(options, demo=False, tui_config=TuiConfig())

    async def _drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for _ in range(40):
                await pilot.pause(delay=0.05)
                if app.snapshot is not None and app.snapshot.refresh_started_at:
                    break

    asyncio.run(_drive())
    snapshot = app.snapshot
    assert snapshot is not None
    assert snapshot.refresh_started_at is not None
