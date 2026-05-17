"""CLI-level tests for `caliper dashboard`: overwrite hint + headless --open fallback."""

from __future__ import annotations

import json
import webbrowser as _webbrowser

from typer.testing import CliRunner

from caliper.cli import app

runner = CliRunner()


def _write_session(tmp_path):
    projects = tmp_path / "claude" / "projects" / "-tmp-project"
    projects.mkdir(parents=True)
    row = {
        "type": "assistant",
        "sessionId": "s1",
        "uuid": "e-1",
        "parentUuid": "",
        "timestamp": "2026-05-12T10:00:00.000Z",
        "cwd": "/tmp/p",
        "requestId": "r-1",
        "message": {
            "id": "m-1",
            "role": "assistant",
            "model": "claude-sonnet-4-6-20260501",
            "content": [{"type": "tool_use", "name": "Read", "input": {}}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
    }
    (projects / "session.jsonl").write_text(json.dumps(row) + "\n")


def _common_args(tmp_path):
    return [
        "--since",
        "2026-05-12",
        "--until",
        "2026-05-13",
        "--tz",
        "UTC",
        "--session-root",
        str(tmp_path / "missing-codex"),
        "--state-db",
        str(tmp_path / "missing-state.sqlite"),
        "--codex-config",
        str(tmp_path / "missing-config.toml"),
        "--include-vendor",
        "claude-code",
        "--no-parse-cache",
        "--no-deltas",
    ]


def test_dashboard_overwrite_hint(monkeypatch, tmp_path) -> None:
    _write_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    out = tmp_path / "report.html"

    first = runner.invoke(app, ["dashboard", "--output", str(out), *_common_args(tmp_path)])
    assert first.exit_code == 0, first.output
    assert "(overwritten)" not in first.output
    assert "Wrote" in first.output

    second = runner.invoke(app, ["dashboard", "--output", str(out), *_common_args(tmp_path)])
    assert second.exit_code == 0, second.output
    assert "(overwritten)" in second.output


def test_dashboard_headless_open_fallback(monkeypatch, tmp_path) -> None:
    """If the browser can't open, the CLI prints a clear fallback line."""
    _write_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    out = tmp_path / "headless.html"

    # Force webbrowser.open to return False (simulates a headless environment).
    monkeypatch.setattr(_webbrowser, "open", lambda *args, **kwargs: False)

    result = runner.invoke(
        app,
        ["dashboard", "--output", str(out), "--open", *_common_args(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "Could not open a browser" in result.output
    assert str(out) in result.output


def test_dashboard_headless_open_exception(monkeypatch, tmp_path) -> None:
    """If webbrowser raises, the CLI still degrades gracefully."""
    _write_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    out = tmp_path / "broken.html"

    def _raise(*args, **kwargs):
        raise _webbrowser.Error("no browser")

    monkeypatch.setattr(_webbrowser, "open", _raise)

    result = runner.invoke(
        app,
        ["dashboard", "--output", str(out), "--open", *_common_args(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "Could not open a browser" in result.output


def test_dashboard_themes_render(monkeypatch, tmp_path) -> None:
    _write_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    for theme in ("dark", "light", "print"):
        out = tmp_path / f"{theme}.html"
        result = runner.invoke(
            app,
            ["dashboard", "--theme", theme, "--output", str(out), *_common_args(tmp_path)],
        )
        assert result.exit_code == 0, f"{theme}: {result.output}"
        html = out.read_text()
        assert f'data-theme="{theme}"' in html


def test_dashboard_demo_renders_without_local_logs(tmp_path) -> None:
    out = tmp_path / "demo.html"
    result = runner.invoke(app, ["dashboard", "--demo", "--output", str(out)])

    assert result.exit_code == 0, result.output
    html = out.read_text()
    assert "Caliper" in html
    for needle in ("://", "<script", "<link"):
        assert needle not in html


def test_dashboard_invalid_theme_errors(monkeypatch, tmp_path) -> None:
    _write_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    out = tmp_path / "x.html"
    result = runner.invoke(
        app,
        [
            "dashboard",
            "--theme",
            "purple-haze",
            "--output",
            str(out),
            *_common_args(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "must be one of" in result.output
