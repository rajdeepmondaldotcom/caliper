"""Tier-override and rates-file behavior."""

from __future__ import annotations

import datetime as dt
import json

from typer.testing import CliRunner

from caliper.cli import app

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _fixture(tmp_path) -> tuple:
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
                    "cached_input_tokens": 0,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    until = (now + dt.timedelta(seconds=1)).isoformat()
    return session_root, state_db, until, tmp_path / "missing.toml", now


def test_rates_file_overrides_credit_cost(tmp_path) -> None:
    """Local rates file overrides credit pricing."""
    session_root, state_db, until, missing_cfg, _now = _fixture(tmp_path)
    rates_file = tmp_path / "rates.json"
    rates_file.write_text(
        json.dumps(
            {
                "credits": {
                    "gpt-5.5": {"input": 1.0, "cached_input": 0.1, "output": 1.0},
                },
            }
        )
    )
    result = runner.invoke(
        app,
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
            "--rates-file",
            str(rates_file),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # 1000 input × 1.0 + 100 output × 1.0 = 1100 micro-credits → 0.0011 credits.
    assert round(payload["totals"]["standard_credits"], 6) == round(1100 / 1_000_000, 6)


def test_cli_service_tier_overrides_logged_value(tmp_path) -> None:
    """--service-tier cli flag wins over logged tier."""
    session_root, state_db, until, missing_cfg, _ = _fixture(tmp_path)
    result = runner.invoke(
        app,
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
            "--service-tier",
            "fast",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["service_tiers"] == ["fast"]
    assert payload["metadata"]["tier_sources"] == {"cli-override": 1}


def test_tier_override_file_by_session_match(tmp_path) -> None:
    """An override-file entry keyed by session filename wins over logged tier."""
    session_root, state_db, until, missing_cfg, _ = _fixture(tmp_path)
    overrides_file = tmp_path / "overrides.json"
    overrides_file.write_text(
        json.dumps(
            {
                "overrides": [
                    {
                        "session": "rollout-2026-05-12T00-00-00-test.jsonl",
                        "service_tier": "fast",
                    }
                ]
            }
        )
    )
    result = runner.invoke(
        app,
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
            "--tier-overrides",
            str(overrides_file),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["service_tiers"] == ["fast"]
    assert payload["metadata"]["tier_sources"] == {"override-file": 1}


def test_tier_override_file_by_date_window(tmp_path) -> None:
    """An override-file entry keyed by start/end window matches events inside it."""
    session_root, state_db, until, missing_cfg, now = _fixture(tmp_path)
    overrides_file = tmp_path / "overrides.json"
    start = (now - dt.timedelta(minutes=1)).isoformat()
    end = (now + dt.timedelta(minutes=1)).isoformat()
    overrides_file.write_text(
        json.dumps(
            {
                "overrides": [
                    {"start": start, "end": end, "service_tier": "fast"},
                ]
            }
        )
    )
    result = runner.invoke(
        app,
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
            "--tier-overrides",
            str(overrides_file),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["service_tiers"] == ["fast"]
    assert payload["metadata"]["tier_sources"] == {"override-file": 1}


def test_malformed_rates_file_exits_with_error(tmp_path) -> None:
    session_root, state_db, until, missing_cfg, _ = _fixture(tmp_path)
    bad = tmp_path / "bad-rates.json"
    bad.write_text("{ not valid json")
    result = runner.invoke(
        app,
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
            "--rates-file",
            str(bad),
            "--format",
            "json",
        ],
    )
    assert result.exit_code != 0
