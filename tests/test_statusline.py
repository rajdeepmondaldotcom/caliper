from __future__ import annotations

import datetime as dt
import json

from typer.testing import CliRunner

from caliper.cli import app

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _fixture(tmp_path) -> list[str]:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-statusline.jsonl",
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
    return [
        "--days",
        "7",
        "--until",
        (now + dt.timedelta(seconds=1)).isoformat(),
        "--session-root",
        str(session_root),
        "--state-db",
        str(state_db),
        "--codex-config",
        str(tmp_path / "missing.toml"),
    ]


def test_statusline_text_is_single_compact_line(tmp_path) -> None:
    result = runner.invoke(app, ["statusline", *_fixture(tmp_path)])

    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert len(lines) == 1
    assert "gpt-5.5/standard" in lines[0]
    assert "project project-alpha" in lines[0]
    assert "today" in lines[0]
    assert "7d" in lines[0]
    assert "5h" in lines[0]
    assert "weekly" in lines[0]
    assert "cache 50%" in lines[0]


def test_statusline_json_exposes_latest_usage_and_limit_windows(tmp_path) -> None:
    result = runner.invoke(app, ["statusline", *_fixture(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["events"] == 1
    assert payload["sessions"] == 1
    assert payload["latest"]["model"] == "gpt-5.5"
    assert payload["latest"]["service_tier"] == "standard"
    assert payload["latest"]["project"] == "/tmp/project-alpha"
    assert payload["top_project"]["label"] == "/tmp/project-alpha"
    assert payload["today"]["cache_ratio"] == 0.5
    assert payload["today"]["credits_exact"]
    assert payload["rate_limits"]["primary"]["limit_id"] == "codex"
    assert payload["subscription"]["plans"][0]["slug"] == "pro"
