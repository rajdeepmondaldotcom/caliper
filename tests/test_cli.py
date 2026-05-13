from __future__ import annotations

import datetime as dt
import json

from typer.testing import CliRunner

from caliper.cli import app

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def test_daily_json_cli_with_fixture_logs(tmp_path) -> None:
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

    result = runner.invoke(
        app,
        [
            "daily",
            "--days",
            "1",
            "--until",
            (now + dt.timedelta(seconds=1)).isoformat(),
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "daily"
    assert payload["totals"]["total_tokens"] == 1100
    assert payload["totals"]["usage_sources"] == ["last_token_usage"]
    assert payload["metadata"]["tier_sources"] == {"logged": 1}
    assert payload["metadata"]["warning_count"] == 0
    assert payload["rate_limit_samples"][0]["primary_used_percent"] == 25.0


def test_doctor_cli_reports_paths(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    session_root.mkdir()
    state_db = tmp_path / "state.sqlite"
    state_db.write_text("")
    config = tmp_path / "config.toml"
    config.write_text("")

    result = runner.invoke(
        app,
        [
            "doctor",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(config),
        ],
    )

    # Doctor returns severity-based exit; fixture has empty sqlite so warn is acceptable.
    assert result.exit_code in {0, 1}
    assert "Session root" in result.output
    assert "State DB" in result.output


def test_session_json_hides_prompt_labels_by_default(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-private.jsonl",
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

    result = runner.invoke(
        app,
        [
            "session",
            "--days",
            "1",
            "--until",
            (now + dt.timedelta(seconds=1)).isoformat(),
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Synthetic private prompt" not in result.output
    payload = json.loads(result.output)
    assert payload["breakdowns"][0]["label"].endswith("private")


def test_invalid_format_exits_with_usage_error() -> None:
    result = runner.invoke(app, ["daily", "--format", "xml"])

    assert result.exit_code == 2
    assert "--output-format must be one of" in result.output
