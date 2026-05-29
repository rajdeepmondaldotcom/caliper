"""CLI-level tests for `caliper dashboard`: overwrite hint + headless --open fallback."""

from __future__ import annotations

import json
import webbrowser as _webbrowser
from pathlib import Path
from urllib.parse import urlparse

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
    assert "Building dashboard: parsing local AI logs..." in first.output
    assert "(overwritten)" not in first.output
    assert "Wrote" in first.output

    second = runner.invoke(app, ["dashboard", "--output", str(out), *_common_args(tmp_path)])
    assert second.exit_code == 0, second.output
    assert "(overwritten)" in second.output


def test_dashboard_default_prints_html_when_stdout_is_not_tty(tmp_path) -> None:
    result = runner.invoke(app, ["dashboard", "--demo"])

    assert result.exit_code == 0, result.output
    assert result.output.startswith("<!doctype html>")
    assert "Wrote" not in result.output


def test_dashboard_safe_share_alias_writes_safe_file(tmp_path) -> None:
    out = tmp_path / "safe.html"

    result = runner.invoke(app, ["dashboard", "--demo", "--safe-share", "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert "share-safe" in result.output
    html = out.read_text(encoding="utf-8")
    assert 'data-share-safe="true"' in html
    assert 'data-privacy="always"' in html
    assert "api-server" not in html
    assert "Project 1" in html


def test_dashboard_respects_config_privacy_off(monkeypatch, tmp_path) -> None:
    # A config that sets privacy="off" is honored: local-only render with real
    # labels. (Earlier versions force-flipped a generated "off" config to
    # "always"; that override is gone now that "off" is the intended default.)
    user_config = tmp_path / "config.toml"
    user_config.write_text(
        """\
[dashboard]
privacy = "off"
"""
    )
    monkeypatch.setattr("caliper.config.USER_CONFIG", user_config)
    monkeypatch.setattr("caliper.config.LOCAL_CONFIG", tmp_path / "missing-local.toml")
    out = tmp_path / "local.html"

    result = runner.invoke(app, ["dashboard", "--demo", "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert "ignoring" not in result.output
    html = out.read_text(encoding="utf-8")
    assert 'data-share-safe="false"' in html
    assert 'data-privacy="off"' in html


def test_dashboard_no_share_safe_keeps_local_labels(tmp_path) -> None:
    out = tmp_path / "local.html"

    result = runner.invoke(app, ["dashboard", "--demo", "--no-share-safe", "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert "local-only" in result.output
    html = out.read_text(encoding="utf-8")
    assert 'data-share-safe="false"' in html
    assert 'data-privacy="off"' in html
    assert "api-server" in html


def test_evidence_json_redacts_parser_issue_paths(monkeypatch, tmp_path) -> None:
    root = tmp_path / "cursor"
    project = root / "projects" / "project-alpha" / "session.jsonl"
    project.parent.mkdir(parents=True)
    project.write_text(
        json.dumps({"role": "assistant", "message": {"content": ["no token counts here"]}}) + "\n"
    )
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(root))

    result = runner.invoke(
        app,
        [
            "evidence",
            "--format",
            "json",
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
            "cursor",
            "--no-parse-cache",
        ],
    )

    assert result.exit_code == 0, result.output
    assert str(project) not in result.output
    payload = json.loads(result.output)
    issue = payload["evidence"]["parser_issues"][0]
    assert issue["examples"] == ["<redacted-path>"]


def test_dashboard_default_opens_browser_for_interactive_terminal(monkeypatch, tmp_path) -> None:
    opened: list[str] = []

    monkeypatch.setattr("caliper.config.USER_CONFIG", tmp_path / "missing-user-config.toml")
    monkeypatch.setattr("caliper.config.LOCAL_CONFIG", tmp_path / "missing-local-config.toml")
    monkeypatch.setattr("caliper.cli._dashboard_stdout_is_interactive", lambda: True)
    monkeypatch.setattr(
        _webbrowser,
        "open",
        lambda url, *args, **kwargs: opened.append(url) or True,
    )

    # Redirect the configured output_dir into the per-test tmp_path so the
    # generated file doesn't litter the real ~/Downloads folder.
    from caliper.config import DashboardConfig
    from caliper.config import load_dashboard_config as real_loader

    def fake_loader(_loaded):
        cfg = real_loader(_loaded)
        return DashboardConfig(
            theme=cfg.theme,
            rhythm=cfg.rhythm,
            density=cfg.density,
            privacy=cfg.privacy,
            show_paths=cfg.show_paths,
            output_dir=str(tmp_path),
            filename_template=cfg.filename_template,
            timestamp_format=cfg.timestamp_format,
            open_after=cfg.open_after,
            default_days=cfg.default_days,
        )

    monkeypatch.setattr("caliper.config.load_dashboard_config", fake_loader)

    result = runner.invoke(app, ["dashboard", "--demo"])

    assert result.exit_code == 0, result.output
    assert "<!doctype html>" not in result.output
    assert "Wrote" in result.output
    assert "Opened" in result.output
    assert opened
    opened_path = Path(urlparse(opened[0]).path)
    # Default privacy is now "off" (local-only real labels), so the filename
    # stays clean — no privacy suffix. Redacted exports get a -privacy-* tag.
    assert opened_path.name.startswith("caliper-dashboard-")
    assert opened_path.name.endswith(".html")
    assert "privacy-" not in opened_path.name
    assert opened_path.exists()
    assert opened_path.read_text(encoding="utf-8").startswith("<!doctype html>")
    # Cleanup the generated file so re-running tests doesn't litter ~/Downloads.
    opened_path.unlink(missing_ok=True)


def test_dashboard_stdout_flag_keeps_raw_html_explicit(monkeypatch) -> None:
    opened: list[str] = []

    monkeypatch.setattr("caliper.cli._dashboard_stdout_is_interactive", lambda: True)
    monkeypatch.setattr(
        _webbrowser,
        "open",
        lambda url, *args, **kwargs: opened.append(url) or True,
    )

    result = runner.invoke(app, ["dashboard", "--demo", "--stdout"])

    assert result.exit_code == 0, result.output
    assert result.output.startswith("<!doctype html>")
    assert not opened


def test_dashboard_stdout_verdict_summarises_cost_trend_and_top_fix(monkeypatch, tmp_path) -> None:
    """After writing the HTML file, ``caliper dashboard`` prints a short
    stdout verdict so a programmer who runs the CLI sees the headline
    number (and the top fix) without opening the file."""
    monkeypatch.setattr("caliper.cli._dashboard_stdout_is_interactive", lambda: True)
    monkeypatch.setattr(
        _webbrowser,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not open")),
    )
    out = tmp_path / "report.html"
    result = runner.invoke(app, ["dashboard", "--demo", "--output", str(out)])

    assert result.exit_code == 0, result.output
    # File line still goes through, unchanged.
    assert "Wrote" in result.output
    # Verdict line: "Caliper · <window> · $<cost> · trend <±X.Y>%"
    assert "Caliper · " in result.output
    assert " · trend " in result.output
    # Re-render hint line includes the theme + share-safe state.
    assert "Theme:" in result.output
    assert "re-render: caliper dashboard --open" in result.output


def test_dashboard_quiet_suppresses_stdout_verdict(monkeypatch, tmp_path) -> None:
    """``--quiet`` silences both the existing 'Wrote ...' line AND the new
    verdict, keeping the CLI scriptable."""
    monkeypatch.setattr("caliper.cli._dashboard_stdout_is_interactive", lambda: True)
    monkeypatch.setattr(
        _webbrowser,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not open")),
    )
    out = tmp_path / "report.html"
    result = runner.invoke(app, ["dashboard", "--demo", "--output", str(out), "--quiet"])

    assert result.exit_code == 0, result.output
    # Verdict line must NOT appear under --quiet.
    assert "Caliper · " not in result.output
    assert "Theme:" not in result.output
    # File was still written.
    assert out.exists()


def test_dashboard_stdout_pipe_skips_verdict_to_keep_html_clean(monkeypatch) -> None:
    """When the user pipes HTML to stdout (``--stdout`` or default
    non-interactive), the verdict must NOT pollute the stream — it's
    HTML-only territory."""
    monkeypatch.setattr("caliper.cli._dashboard_stdout_is_interactive", lambda: True)
    result = runner.invoke(app, ["dashboard", "--demo", "--stdout"])

    assert result.exit_code == 0, result.output
    assert result.output.startswith("<!doctype html>")
    # Verdict prefix must not appear anywhere in the HTML stream.
    assert "Caliper · " not in result.output
    assert "re-render: caliper dashboard" not in result.output


def test_dashboard_output_does_not_open_without_open_flag(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("caliper.cli._dashboard_stdout_is_interactive", lambda: True)
    monkeypatch.setattr(
        _webbrowser,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not open")),
    )
    out = tmp_path / "report.html"

    result = runner.invoke(app, ["dashboard", "--demo", "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert "Wrote" in result.output
    assert "Opened" not in result.output
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_dashboard_stdout_rejects_output_or_open(tmp_path) -> None:
    out = tmp_path / "report.html"

    with_output = runner.invoke(app, ["dashboard", "--demo", "--stdout", "--output", str(out)])
    assert with_output.exit_code != 0
    assert "cannot be combined" in with_output.output

    with_open = runner.invoke(app, ["dashboard", "--demo", "--stdout", "--open"])
    assert with_open.exit_code != 0
    assert "cannot be combined" in with_open.output


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


def test_dashboard_days_still_renders_rolling_windows(monkeypatch, tmp_path) -> None:
    _write_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    out = tmp_path / "rolling.html"

    result = runner.invoke(
        app,
        [
            "dashboard",
            "--days",
            "7",
            "--until",
            "2026-05-13T00:00:00Z",
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
            "--output",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    html = out.read_text()
    # The v2 design surfaces the selected report window in the masthead window
    # badge. The rolling 7/30/90-day rollups are no longer rendered as a
    # dedicated section, but the rolling parse still runs (and is checked by
    # adapter tests).
    assert "Last 7 days" in html


def test_dashboard_loads_once_for_selected_and_rolling_windows(monkeypatch, tmp_path) -> None:
    """Dashboard should scan the superset window once, then scope in memory."""
    from caliper.models import LoadResult

    calls = 0

    def fake_load_usage(_options, *, progress=None):
        nonlocal calls
        del progress
        calls += 1
        return LoadResult(
            events=[],
            duplicates=0,
            tier_sources={},
            plan_types=set(),
            rate_limit_samples=[],
            warnings=[],
        )

    monkeypatch.setattr("caliper.cli._safe_load_usage", fake_load_usage)
    out = tmp_path / "single-load.html"
    result = runner.invoke(
        app,
        [
            "dashboard",
            "--days",
            "7",
            "--until",
            "2026-05-13T00:00:00Z",
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
            "--output",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == 1
    assert out.exists()


def test_dashboard_demo_renders_without_local_logs(tmp_path) -> None:
    out = tmp_path / "demo.html"
    result = runner.invoke(app, ["dashboard", "--demo", "--output", str(out)])

    assert result.exit_code == 0, result.output
    html = out.read_text()
    assert "Caliper" in html
    # v2 with interactive mode (default): exactly one inline <script> tag
    # for the toggle controller. The CI privacy gate forbids any network
    # APIs inside it.
    assert html.count("<script>") <= 1
    # `://` covers any external URL — the only `<link>` present is the
    # inline-data-URI favicon, which carries no network risk.
    for needle in ("://", " src=", "fetch(", "XMLHttpRequest", "import("):
        assert needle not in html


def test_dashboard_rhythm_terminal(tmp_path) -> None:
    out = tmp_path / "term.html"
    result = runner.invoke(
        app, ["dashboard", "--demo", "--rhythm", "terminal", "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    html = out.read_text()
    assert 'data-rhythm="terminal"' in html
    assert "OFFLINE" in html
    assert ">Index<" in html


def test_dashboard_rhythm_invalid(tmp_path) -> None:
    out = tmp_path / "x.html"
    result = runner.invoke(
        app, ["dashboard", "--demo", "--rhythm", "purple-haze", "--output", str(out)]
    )
    assert result.exit_code != 0
    assert "must be one of" in result.output


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
