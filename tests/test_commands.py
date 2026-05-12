"""Smoke tests for every command — exit 0 + key fields on a shared fixture."""

from __future__ import annotations

import datetime as dt
import json

from typer.testing import CliRunner

from codex_meter.cli import app

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _build(tmp_path) -> tuple:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-test.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 500,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    return (
        session_root,
        state_db,
        (now + dt.timedelta(seconds=1)).isoformat(),
        tmp_path / "missing.toml",
    )


def _common_args(tmp_path) -> list:
    session_root, state_db, until, missing_cfg = _build(tmp_path)
    return [
        "--days",
        "30",
        "--until",
        until,
        "--session-root",
        str(session_root),
        "--state-db",
        str(state_db),
        "--codex-config",
        str(missing_cfg),
    ]


def test_weekly_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["weekly", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "weekly"
    assert payload["totals"]["total_tokens"] == 1100


def test_monthly_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["monthly", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "monthly"
    assert payload["totals"]["total_tokens"] == 1100


def test_session_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["session", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "session"
    assert payload["totals"]["total_tokens"] == 1100
    assert len(payload["breakdowns"]) == 1


def test_project_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["project", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "project"
    assert payload["breakdowns"][0]["label"] == "/tmp/project-alpha"


def test_models_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["models", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "models"
    assert "gpt-5.5" in payload["breakdowns"][0]["label"]


def test_limits_smoke(tmp_path) -> None:
    """limits has its own flag surface — no --format option today."""
    session_root, state_db, until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "limits",
            "--days",
            "30",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Codex Meter - Limits" in result.output


def test_doctor_smoke(tmp_path) -> None:
    session_root, state_db, _until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "doctor",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    # Doctor exits with status reflecting worst check (warn = 1 in fixture).
    assert result.exit_code in {0, 1}, result.output
    assert "Codex Meter - Doctor" in result.output
    assert "Session root" in result.output


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_invalid_since_before_until(tmp_path) -> None:
    session_root, state_db, _until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "daily",
            "--since",
            "2027-01-01",
            "--until",
            "2026-01-01",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code != 0
