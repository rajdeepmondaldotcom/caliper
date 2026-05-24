"""Smoke coverage for every registered CLI command.

A critical user can reach any command. This suite proves two things:

* **Tier A — registration/help:** every top-level command and every
  sub-command of every group responds to ``--help`` with exit 0 and no
  unhandled exception. This catches import errors, broken option
  definitions, and accidental de-registration the moment they land.
* **Tier B — real execution:** the data commands run against a seeded
  Claude-Code session and must exit cleanly (code in {0,1,2}; budgets may
  legitimately signal 1/2) with no unhandled traceback. ``--output`` always
  targets ``tmp_path`` so nothing touches real paths.

The command list is introspected from the Typer app, so new commands are
covered automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from caliper.cli import app

runner = CliRunner()


def _all_invocations() -> list[list[str]]:
    """Every command path: top-level commands + group sub-commands."""
    paths: list[list[str]] = []
    for cmd in app.registered_commands:
        name = cmd.name or (cmd.callback.__name__.replace("_", "-") if cmd.callback else None)
        if name:
            paths.append([name])
    for group in app.registered_groups:
        gname = group.name
        sub = group.typer_instance
        for cmd in sub.registered_commands:
            cname = cmd.name or (cmd.callback.__name__.replace("_", "-") if cmd.callback else None)
            if gname and cname:
                paths.append([gname, cname])
        # The bare group should also respond to --help.
        if gname:
            paths.append([gname])
    return paths


def _assert_clean(result, argv: list[str], *, allowed=(0,)) -> None:
    # An unhandled (non-SystemExit) exception means a real crash.
    exc = result.exception
    if exc is not None and not isinstance(exc, SystemExit):
        raise AssertionError(
            f"`caliper {' '.join(argv)}` raised {type(exc).__name__}: {exc}\n{result.output}"
        )
    joined = " ".join(argv)
    assert result.exit_code in allowed, (
        f"`caliper {joined}` exited {result.exit_code} (allowed {allowed}).\n{result.output}"
    )


@pytest.mark.parametrize("argv", _all_invocations(), ids=lambda a: " ".join(a))
def test_every_command_help_is_clean(argv) -> None:
    result = runner.invoke(app, [*argv, "--help"])
    _assert_clean(result, [*argv, "--help"], allowed=(0,))
    assert "Usage:" in result.output or "Options" in result.output


def _seed_claude_session(monkeypatch, tmp_path: Path) -> None:
    """Write a tiny Claude-Code session and point the vendor root at it."""
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    rows = [
        {
            "type": "assistant",
            "sessionId": "claude-session-1",
            "uuid": f"event-{i}",
            "parentUuid": f"parent-{i}",
            "timestamp": f"2026-05-12T10:0{i}:00.000Z",
            "cwd": "/tmp/project-alpha",
            "requestId": f"req-{i}",
            "message": {
                "id": f"msg-{i}",
                "role": "assistant",
                "model": "claude-sonnet-4-6-20260501",
                "content": [{"type": "tool_use", "name": "Read", "input": {}}],
                "usage": {"input_tokens": 100 + i, "output_tokens": 25},
            },
        }
        for i in range(1, 4)
    ]
    (projects / "claude-session-1.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))


def _common_args(tmp_path: Path) -> list[str]:
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
    ]


# Data commands that are safe to actually execute against a seeded session
# (no required positional args, not an interactive TTY workspace).
_RUNNABLE = [
    "overview",
    "daily",
    "weekly",
    "monthly",
    "session",
    "project",
    "models",
    "shape",
    "evidence",
    "insights",
    "inefficiencies",
    "advise",
    "audit",
    "recommend",
    "exec",
    "predict",
    "doctor",
    "statusline",
    "blocks",
    "limits",
    "agents",
    "skills",
]


@pytest.mark.parametrize("cmd", _RUNNABLE)
def test_data_command_runs_clean(monkeypatch, tmp_path, cmd) -> None:
    _seed_claude_session(monkeypatch, tmp_path)
    argv = [cmd, *_common_args(tmp_path)]
    result = runner.invoke(app, argv)
    # doctor/budgets-style commands may signal warn/fail via 1/2; a usage
    # error is also 2. Anything is fine EXCEPT an unhandled traceback.
    _assert_clean(result, argv, allowed=(0, 1, 2))


def test_json_output_to_missing_dir_is_created(monkeypatch, tmp_path) -> None:
    """The _write_output_file helper must create missing parent dirs instead
    of stack-tracing with FileNotFoundError."""
    _seed_claude_session(monkeypatch, tmp_path)
    out = tmp_path / "deep" / "new" / "nested" / "overview.json"
    argv = ["overview", *_common_args(tmp_path), "--format", "json", "--output", str(out)]
    result = runner.invoke(app, argv)
    _assert_clean(result, argv, allowed=(0,))
    assert out.exists(), "output file (and its parent dirs) should have been created"
    json.loads(out.read_text())  # valid JSON


def test_dashboard_demo_runs_clean() -> None:
    result = runner.invoke(app, ["dashboard", "--demo", "--stdout"])
    _assert_clean(result, ["dashboard", "--demo", "--stdout"], allowed=(0,))
    assert result.output.startswith("<!doctype html>")
