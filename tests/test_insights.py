from __future__ import annotations

import datetime as dt
import json

from typer.testing import CliRunner

from caliper.cli import app

from .conftest import make_state_db, token_event, write_session

runner = CliRunner()


def _fixture(tmp_path) -> tuple:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-insights.jsonl",
        [
            {
                "type": "turn_context",
                "timestamp": "2026-05-12T00:00:00Z",
                "payload": {"model": "gpt-5.5"},
            },
            token_event(
                now,
                {
                    "input_tokens": 10_000,
                    "cached_input_tokens": 9_000,
                    "output_tokens": 1_000,
                    "reasoning_output_tokens": 250,
                    "total_tokens": 11_000,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    return session_root, state_db, tmp_path / "missing.toml"


def test_insights_json_reports_cache_tier_and_project_concentration(tmp_path) -> None:
    session_root, state_db, missing_cfg = _fixture(tmp_path)
    result = runner.invoke(
        app,
        [
            "insights",
            "--days",
            "1",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    titles = {item["title"] for item in payload["insights"]}
    assert "High cache reuse" in titles
    assert "Service tier inferred" in titles
    assert "Spend concentrated in one project" in titles


def test_insights_markdown_renders_actions(tmp_path) -> None:
    session_root, state_db, missing_cfg = _fixture(tmp_path)
    result = runner.invoke(
        app,
        [
            "insights",
            "--days",
            "1",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "--format",
            "markdown",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "| Severity | Insight | Detail | Action |" in result.output
    assert "caliper project" in result.output
