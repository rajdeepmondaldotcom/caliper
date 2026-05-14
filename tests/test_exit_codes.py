from __future__ import annotations

import datetime as dt

from typer.testing import CliRunner

from caliper.cli import app

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _fixture(tmp_path):
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-exit.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(now, {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    return session_root, state_db, now


def test_doctor_exit_code_matrix_warn_or_ok(tmp_path) -> None:
    session_root, state_db, _now = _fixture(tmp_path)

    result = runner.invoke(
        app,
        [
            "doctor",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
        ],
    )

    assert result.exit_code in {0, 1}


def test_budgets_check_exit_code_warn(tmp_path) -> None:
    session_root, state_db, _now = _fixture(tmp_path)
    config = tmp_path / ".caliper.toml"
    config.write_text("[budgets]\ndaily_cost_usd = 0.0001\n")

    result = runner.invoke(
        app,
        [
            "budgets",
            "check",
            "--config",
            str(config),
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
        ],
    )

    assert result.exit_code in {1, 2}
