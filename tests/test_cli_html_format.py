"""Smoke matrix: `--format html` works for every grouped command.

Each command's HTML output must:

* exit 0 against an empty session root,
* start with ``<!doctype html>``,
* be safe-by-default (``data-share-safe="true"``),
* be self-contained (no external CSS/JS/font references),
* write to ``--out file`` without echoing to stdout when ``--out`` is set.

The v2 dashboard redesign removed the audience-lens system; the
per-command ``lens_for_command`` label is kept for grouping logic but is
no longer surfaced as a ``data-lens`` attribute. Tests that previously
asserted on that attribute now just verify the chrome scaffolding.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from caliper.cli import app
from caliper.html_export import lens_for_command


@pytest.fixture
def setup_environment(monkeypatch, tmp_path):
    monkeypatch.setattr("caliper.config.USER_CONFIG", tmp_path / "missing-user-config.toml")
    monkeypatch.setattr("caliper.config.LOCAL_CONFIG", tmp_path / "missing-local-config.toml")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    state_db = tmp_path / "state.db"
    codex_config = tmp_path / "codex.toml"
    codex_config.write_text("")
    return {
        "session_root": str(codex_home),
        "state_db": str(state_db),
        "codex_config": str(codex_config),
    }


def _base_window_args() -> list[str]:
    return ["--since", "2026-04-01", "--until", "2026-05-01"]


def _common_args(env: dict[str, str]) -> list[str]:
    return [
        "--session-root",
        env["session_root"],
        "--state-db",
        env["state_db"],
        "--codex-config",
        env["codex_config"],
    ]


def _body_tag(html: str) -> str:
    start = html.index("<body ")
    end = html.index(">", start)
    return html[start : end + 1]


HTML_COMMANDS = [
    "overview",
    "daily",
    "weekly",
    "monthly",
    "session",
    "project",
    "models",
    "insights",
    "limits",
    "tail",
]


# forecast / compare / whatif need a fuller invocation: they don't take
# generic `--since/--until` and assemble their own windows.
EXTRA_HTML_COMMANDS = ["forecast", "compare", "whatif"]


@pytest.mark.parametrize("command", HTML_COMMANDS)
def test_html_format_grouped_command_emits_dashboard_chrome(
    command: str, setup_environment
) -> None:
    """The seven core grouped commands all emit dashboard HTML on stdout."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            command,
            "--format",
            "html",
            *_common_args(setup_environment),
            *_base_window_args(),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("<!doctype html>"), result.stdout[:200]
    assert "</html>" in result.stdout
    # lens_for_command is still importable but no longer surfaced as an
    # attribute — keep the import live so refactors don't silently break it.
    assert lens_for_command(command) in {"executive", "engineer", "finance", "audit"}
    assert 'data-share-safe="true"' in result.stdout


@pytest.mark.parametrize("command", HTML_COMMANDS)
def test_html_format_writes_to_file_and_keeps_stdout_clean(
    command: str, setup_environment, tmp_path
) -> None:
    """``--out file`` writes the HTML to disk; stdout has nothing."""
    out_file = tmp_path / f"{command}.html"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            command,
            "--format",
            "html",
            "--out",
            str(out_file),
            *_common_args(setup_environment),
            *_base_window_args(),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert content.startswith("<!doctype html>")
    assert "</html>" in content
    # stdout is empty when --out is set
    assert result.stdout.strip() == ""


def test_html_format_share_safe_can_be_disabled(setup_environment) -> None:
    """``--no-share-safe`` honors the override."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "overview",
            "--format",
            "html",
            "--no-share-safe",
            *_common_args(setup_environment),
            *_base_window_args(),
        ],
    )
    assert result.exit_code == 0, result.output
    assert 'data-share-safe="false"' in result.stdout


def test_html_format_self_contained_no_external_resources(setup_environment, tmp_path) -> None:
    """No CDN refs, no remote fonts, no remote scripts."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "overview",
            "--format",
            "html",
            *_common_args(setup_environment),
            *_base_window_args(),
        ],
    )
    assert result.exit_code == 0
    html = result.stdout
    for pattern in (
        'src="http://',
        "src='http://",
        'src="https://',
        "src='https://",
        'href="http://',
        "href='http://",
        'href="https://',
        "href='https://",
        '<link rel="stylesheet"',
        "<link rel='stylesheet'",
    ):
        assert pattern not in html, f"Found remote reference: {pattern}"


def test_html_format_dashboard_command_default_privacy(
    setup_environment,
) -> None:
    """``caliper dashboard`` defaults to a local-only render with real labels."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dashboard",
            "--stdout",
            *_common_args(setup_environment),
        ],
    )
    assert result.exit_code == 0, result.output
    # Default privacy is "off" (real labels) for your own analysis. Redact for
    # sharing with --privacy always or --share-safe. ``data-share-safe`` mirrors
    # ``privacy == "always"``.
    body_tag = _body_tag(result.stdout)
    assert 'data-privacy="off"' in body_tag
    assert 'data-share-safe="false"' in body_tag


def test_html_format_dashboard_command_privacy_always(setup_environment) -> None:
    """``--privacy always`` reproduces the legacy redact-everywhere behaviour."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dashboard",
            "--stdout",
            "--privacy",
            "always",
            *_common_args(setup_environment),
        ],
    )
    assert result.exit_code == 0, result.output
    assert 'data-privacy="always"' in result.stdout
    assert 'data-share-safe="true"' in result.stdout


def test_html_format_with_progress_flag_keeps_stdout_html(setup_environment, tmp_path) -> None:
    """``--progress`` writes the spinner to stderr; the HTML on stdout is intact."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "daily",
            "--format",
            "html",
            "--progress",
            *_common_args(setup_environment),
            *_base_window_args(),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("<!doctype html>")
    assert "</html>" in result.stdout


@pytest.mark.parametrize("command", EXTRA_HTML_COMMANDS)
def test_extra_commands_support_html_format(command: str, setup_environment) -> None:
    """forecast / compare / whatif each emit dashboard HTML."""
    runner = CliRunner()
    extra_args: list[str] = []
    if command == "whatif":
        extra_args = ["--tier", "fast"]
    result = runner.invoke(
        app,
        [
            command,
            "--format",
            "html",
            *extra_args,
            *_common_args(setup_environment),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("<!doctype html>"), result.stdout[:200]
    assert lens_for_command(command) in {"executive", "engineer", "finance", "audit"}
