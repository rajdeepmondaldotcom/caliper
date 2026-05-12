from __future__ import annotations

import csv
import datetime as dt
import io
import json

from typer.testing import CliRunner

from codex_meter.cli import app

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _fixture(tmp_path, model: str = "gpt-5.5", tier: str = "standard") -> tuple:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-test.jsonl",
        [
            turn_context(model=model, service_tier=tier),
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 500,
                    "output_tokens": 100,
                    "reasoning_output_tokens": 25,
                    "total_tokens": 1100,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    until = (now + dt.timedelta(seconds=1)).isoformat()
    return session_root, state_db, until, tmp_path / "missing.toml"


def _invoke(args: list) -> object:
    return runner.invoke(app, args)


def test_daily_json_pins_schema(tmp_path) -> None:
    session_root, state_db, until, missing_cfg = _fixture(tmp_path)
    result = _invoke(
        [
            "daily",
            "--days",
            "1",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "--format",
            "json",
        ]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert set(payload.keys()) == {
        "command",
        "generated_at",
        "window",
        "totals",
        "breakdowns",
        "model_mode",
        "pricing",
        "metadata",
        "rate_limit_samples",
        "warnings",
    }
    assert isinstance(payload["rate_limit_samples"], list)
    assert payload["command"] == "daily"
    assert payload["totals"]["input_tokens"] == 1000
    assert payload["totals"]["cached_input_tokens"] == 500
    assert payload["totals"]["output_tokens"] == 100
    assert payload["totals"]["reasoning_output_tokens"] == 25
    assert payload["totals"]["total_tokens"] == 1100
    assert payload["totals"]["cache_savings_credits"] > 0
    assert payload["totals"]["cache_savings_api_dollars"] > 0
    assert payload["totals"]["events"] == 1
    assert payload["totals"]["models"] == ["gpt-5.5"]
    assert payload["totals"]["service_tiers"] == ["standard"]
    assert payload["pricing"]["mode"] == "model"
    assert payload["metadata"]["tier_sources"] == {"logged": 1}
    assert payload["metadata"]["plan_types"] == ["pro"]
    assert len(payload["breakdowns"]) == 1


def test_table_warns_when_model_has_unpriced_costs(tmp_path) -> None:
    session_root, state_db, until, missing_cfg = _fixture(tmp_path, model="gpt-5.3-codex-spark")
    result = _invoke(
        [
            "daily",
            "--days",
            "1",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ]
    )
    assert result.exit_code == 0, result.output
    assert "no API-dollar rate" in result.output
    assert "partial" in result.output


def test_daily_csv_has_header_and_data(tmp_path) -> None:
    session_root, state_db, until, missing_cfg = _fixture(tmp_path)
    result = _invoke(
        [
            "daily",
            "--days",
            "1",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "--format",
            "csv",
        ]
    )
    assert result.exit_code == 0, result.output
    reader = csv.DictReader(io.StringIO(result.output))
    rows = list(reader)
    assert len(rows) == 1
    assert int(rows[0]["total_tokens"]) == 1100
    assert int(rows[0]["events"]) == 1
    assert rows[0]["models"] == "gpt-5.5"
    assert rows[0]["service_tiers"] == "standard"
    assert set(reader.fieldnames or []) == {
        "key",
        "label",
        "events",
        "input_tokens",
        "cached_input_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
        "credits",
        "standard_credits",
        "api_dollars",
        "pricing_status",
        "unpriced_events",
        "estimated_events",
        "models",
        "service_tiers",
    }


def test_daily_markdown_has_header_row(tmp_path) -> None:
    session_root, state_db, until, missing_cfg = _fixture(tmp_path)
    result = _invoke(
        [
            "daily",
            "--days",
            "1",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "--format",
            "markdown",
        ]
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert lines[0].startswith("| Group |")
    assert "Events" in lines[0]
    assert "Total" in lines[0]
    assert "Input" in lines[0]
    assert "Cached" in lines[0]
    assert "Output" in lines[0]
    assert "Credits" in lines[0]
    assert lines[1].startswith("| --- |")
    assert any("1100" in line for line in lines[2:])
    # Totals row appears at the end with **Total** marker.
    assert lines[-1].startswith("| **Total** |")
    assert "1100" in lines[-1]


def test_daily_table_includes_totals_and_window(tmp_path) -> None:
    session_root, state_db, until, missing_cfg = _fixture(tmp_path)
    result = _invoke(
        [
            "daily",
            "--days",
            "1",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "--format",
            "table",
        ]
    )
    assert result.exit_code == 0, result.output
    assert "Codex Meter - Daily" in result.output
    assert "Window:" in result.output
    assert "gpt-5.5" in result.output
    assert "1,100" in result.output
    assert "Total" in result.output
    assert "Cache savings:" in result.output


def test_daily_table_width_option_prevents_truncation(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-wide.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(
                now,
                {
                    "input_tokens": 1_234_567_890,
                    "cached_input_tokens": 1_000_000_000,
                    "output_tokens": 987_654,
                    "total_tokens": 1_235_555_544,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    result = _invoke(
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
            "--width",
            "240",
        ]
    )
    assert result.exit_code == 0, result.output
    assert "1,234,567,890" in result.output
    assert "1,235,555,544" in result.output
    assert "…" not in result.output


def test_daily_accepts_top_alias(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-top.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(
                now - dt.timedelta(days=1),
                {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            ),
            token_event(now, {"input_tokens": 200, "output_tokens": 20, "total_tokens": 220}),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    result = _invoke(
        [
            "daily",
            "--days",
            "3",
            "--until",
            (now + dt.timedelta(seconds=1)).isoformat(),
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "--top",
            "1",
            "--format",
            "csv",
        ]
    )
    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(io.StringIO(result.output)))
    assert len(rows) == 1


def test_project_table_uses_short_path_label(tmp_path) -> None:
    session_root, state_db, until, missing_cfg = _fixture(tmp_path)
    result = _invoke(
        [
            "project",
            "--days",
            "1",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "--width",
            "140",
        ]
    )
    assert result.exit_code == 0, result.output
    assert "project-alpha" in result.output
    assert "/tmp/project-alpha" not in result.output


def test_daily_json_long_context_pricing(tmp_path) -> None:
    """Long-context (>272K input) doubles input and 1.5x output cost."""
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
                    "input_tokens": 300_000,
                    "cached_input_tokens": 0,
                    "output_tokens": 10_000,
                    "total_tokens": 310_000,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    until = (now + dt.timedelta(seconds=1)).isoformat()

    result = _invoke(
        [
            "daily",
            "--days",
            "1",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "--format",
            "json",
        ]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["breakdowns"][0]["long_context_events"] == 1
    # gpt-5.5: input=$5/M, output=$30/M.
    # Long context doubles input, 1.5x output:
    #   300_000 * 5 * 2 / 1e6 = 3.00
    #   10_000 * 30 * 1.5 / 1e6 = 0.45
    # Total: $3.45
    assert round(payload["totals"]["api_dollars"], 2) == 3.45


def test_daily_json_fast_tier_credit_multiplier(tmp_path) -> None:
    session_root, state_db, until, missing_cfg = _fixture(tmp_path, tier="fast")
    result = _invoke(
        [
            "daily",
            "--days",
            "1",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "--format",
            "json",
        ]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    standard = payload["totals"]["standard_credits"]
    adjusted = payload["totals"]["credits"]
    assert round(adjusted / standard, 4) == 2.5
