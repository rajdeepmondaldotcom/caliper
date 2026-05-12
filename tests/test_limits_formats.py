"""limits command across all output formats."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json

from typer.testing import CliRunner

from codex_meter.cli import app

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _fixture(tmp_path) -> tuple:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-limits.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(
                now,
                {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
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


def _invoke(tmp_path, fmt: str):
    session_root, state_db, until, missing = _fixture(tmp_path)
    return runner.invoke(
        app,
        [
            "limits",
            "--days",
            "1",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing),
            "--format",
            fmt,
        ],
    )


def test_limits_table(tmp_path) -> None:
    result = _invoke(tmp_path, "table")
    assert result.exit_code == 0, result.output
    assert "Codex Meter - Limits" in result.output
    assert "Primary %" in result.output
    assert "Reset In" in result.output
    assert "primary=" not in result.output


def test_limits_json(tmp_path) -> None:
    result = _invoke(tmp_path, "json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "limits"
    assert isinstance(payload["rate_limit_samples"], list)
    assert payload["rate_limit_samples"][0]["primary_used_percent"] == 25.0
    assert payload["rate_limit_samples"][0]["limit_id"] == "codex"


def test_limits_csv(tmp_path) -> None:
    result = _invoke(tmp_path, "csv")
    assert result.exit_code == 0, result.output
    reader = csv.DictReader(io.StringIO(result.output))
    rows = list(reader)
    assert rows
    assert "primary_used_percent" in (reader.fieldnames or [])
    assert "limit_id" in (reader.fieldnames or [])
    assert rows[0]["plan_type"] == "pro"
    assert rows[0]["limit_id"] == "codex"


def test_limits_markdown(tmp_path) -> None:
    result = _invoke(tmp_path, "markdown")
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert lines[0].startswith("| Timestamp |")
    assert "Primary %" in lines[0]


def test_limits_top_limits_reported_samples_not_loaded_events(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-limits-top.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(now, {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}),
            token_event(
                now + dt.timedelta(minutes=1),
                {"input_tokens": 200, "output_tokens": 20, "total_tokens": 220},
            ),
            token_event(
                now + dt.timedelta(minutes=2),
                {"input_tokens": 300, "output_tokens": 30, "total_tokens": 330},
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    result = runner.invoke(
        app,
        [
            "limits",
            "--days",
            "1",
            "--until",
            (now + dt.timedelta(minutes=3)).isoformat(),
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "--format",
            "json",
            "--top",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["events"] == 3
    assert len(payload["rate_limit_samples"]) == 2
