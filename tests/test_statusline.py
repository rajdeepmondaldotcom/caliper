from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from typer.testing import CliRunner

from caliper.cli import app
from caliper.models import ThreadMeta, Usage, UsageEvent
from caliper.pricing import RateCard
from caliper.statusline import _top_project, _window_text
from caliper.windows import WindowState

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
    assert "statusline" not in payload["latest"]["session"]
    assert "," in payload["latest"]["session"]
    assert payload["latest"]["session_id"] == "<redacted-session>"
    assert payload["latest"]["project"] == "<redacted-path>"
    assert payload["top_project"]["label"] == "<redacted-path>"
    assert "/tmp/project-alpha" not in result.output
    assert payload["today"]["cache_ratio"] == 0.5
    assert payload["today"]["cost_usd_exact"]
    assert payload["rate_limits"]["primary"]["limit_id"] == "codex"
    assert payload["subscription"]["plans"][0]["slug"] == "pro"


def test_statusline_json_show_paths_restores_latest_usage_identity(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["statusline", *_fixture(tmp_path), "--format", "json", "--show-paths"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["latest"]["project"] == "/tmp/project-alpha"
    assert payload["top_project"]["label"] == "/tmp/project-alpha"
    assert "statusline" not in payload["latest"]["session"]
    assert payload["latest"]["session_id"] == "2026-05-12T00-00-00-statusline"


def test_statusline_compact_stays_prompt_sized(tmp_path) -> None:
    result = runner.invoke(app, ["statusline", *_fixture(tmp_path), "--compact"])

    assert result.exit_code == 0, result.output
    line = result.output.strip()
    assert len(line) <= 80
    assert "T $" in line
    assert "7d $" in line
    assert "project" not in line


def test_statusline_watch_max_ticks(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "statusline",
            *_fixture(tmp_path),
            "--vendor",
            "openai-codex",
            "--format",
            "json",
            "--watch",
            "0.1",
            "--max-ticks",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len([line for line in result.output.splitlines() if line.strip()]) == 2


def test_statusline_window_text_marks_expired_reset_as_due() -> None:
    state = WindowState(
        window="primary",
        used_percent=28.0,
        window_minutes=300,
        reset_at=dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=1),
        seconds_remaining=0,
        burn_rate_per_hour=None,
        eta_to_100=None,
        samples=1,
        limit_id="codex",
    )

    assert _window_text(state) == "28% reset due"


def test_statusline_top_project_uses_cost_not_sort_order() -> None:
    now = dt.datetime.now(tz=dt.UTC)

    def event(project: str, tokens: int) -> UsageEvent:
        return UsageEvent(
            timestamp=now,
            path=Path(f"{project}.jsonl"),
            session_id=project,
            usage=Usage(input_tokens=tokens, output_tokens=tokens, total_tokens=tokens * 2),
            model="gpt-5.5",
            service_tier="standard",
            tier_source="logged",
            thread=ThreadMeta(cwd=project),
        )

    project, cost = _top_project(
        [event("/tmp/a-expensive", 10_000), event("/tmp/z-cheap", 100)],
        RateCard.load(None, "model"),
    )

    assert project == "/tmp/a-expensive"
    assert cost > 0
