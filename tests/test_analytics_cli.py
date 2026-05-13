from __future__ import annotations

import datetime as dt
import json

from typer.testing import CliRunner

from caliper.cli import app

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _build_fixture(tmp_path, tier: str = "fast") -> tuple:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-test.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier=tier),
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
    missing_cfg = tmp_path / "missing.toml"
    return session_root, state_db, missing_cfg


def test_forecast_table_runs_and_reports_zero_for_empty_dataset(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    session_root.mkdir()
    state_db = tmp_path / "state.sqlite"
    state_db.write_text("")
    missing_cfg = tmp_path / "missing.toml"
    result = runner.invoke(
        app,
        [
            "forecast",
            "--days",
            "7",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Codex Meter - Forecast" in result.output
    assert "API $" in result.output
    assert "Trend" in result.output


def test_forecast_json_reports_required_fields(tmp_path) -> None:
    session_root, state_db, missing_cfg = _build_fixture(tmp_path)
    result = runner.invoke(
        app,
        [
            "forecast",
            "--days",
            "7",
            "--cap",
            "10000",
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
    expected_keys = {
        "unit",
        "days_analyzed",
        "daily_mean",
        "daily_stdev",
        "days_remaining",
        "linear_total",
        "ewma_total",
        "linear_low",
        "linear_high",
        "cap",
        "days_to_cap",
    }
    assert expected_keys <= set(payload.keys())
    assert payload["cap"] == 10000.0
    assert "api_dollars" in payload["projections"]
    assert "sparkline" in payload


def test_tail_json_returns_recent_events(tmp_path) -> None:
    session_root, state_db, missing_cfg = _build_fixture(tmp_path, tier="standard")
    result = runner.invoke(
        app,
        [
            "tail",
            "--n",
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
    assert payload["events"][0]["model"] == "gpt-5.5"
    assert payload["events"][0]["service_tier"] == "standard"


def test_whatif_requires_at_least_one_change(tmp_path) -> None:
    session_root, state_db, missing_cfg = _build_fixture(tmp_path)
    result = runner.invoke(
        app,
        [
            "whatif",
            "--days",
            "1",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code == 2
    assert "tier" in result.output.lower() or "model" in result.output.lower()


def test_whatif_tier_swap_reduces_credits_when_going_from_fast_to_standard(tmp_path) -> None:
    session_root, state_db, missing_cfg = _build_fixture(tmp_path, tier="fast")
    result = runner.invoke(
        app,
        [
            "whatif",
            "--days",
            "1",
            "--tier",
            "standard",
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
    assert payload["actual"]["credits"] > payload["projected"]["credits"]
    assert "credits_exact" in payload["actual"]
    assert "api_dollars_exact" in payload["projected"]
    assert payload["delta"]["credits"] < 0
    assert "credits_exact" in payload["delta"]


def test_whatif_rejects_unknown_model(tmp_path) -> None:
    session_root, state_db, missing_cfg = _build_fixture(tmp_path)
    result = runner.invoke(
        app,
        [
            "whatif",
            "--days",
            "1",
            "--model",
            "gpt-9.9",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code == 2
    assert "rate card" in result.output


def test_compare_returns_balanced_delta(tmp_path) -> None:
    session_root, state_db, missing_cfg = _build_fixture(tmp_path, tier="standard")
    result = runner.invoke(
        app,
        [
            "compare",
            "--a",
            "last 1 days",
            "--b",
            "previous 1 days",
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
    assert {"a", "b", "delta"} <= set(payload.keys())
    assert payload["a"]["credits"] >= 0
    assert "credits_exact" in payload["a"]
    assert payload["b"]["credits"] >= 0
    assert "api_dollars_exact" in payload["delta"]


def test_compare_rejects_unknown_expression(tmp_path) -> None:
    session_root, state_db, missing_cfg = _build_fixture(tmp_path)
    result = runner.invoke(
        app,
        [
            "compare",
            "--a",
            "yesterday at noon",
            "--b",
            "today",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code == 2
    assert "Unrecognized window expression" in result.output
    assert "Try:" in result.output


def test_whatif_reports_noop_tier_swap(tmp_path) -> None:
    session_root, state_db, missing_cfg = _build_fixture(tmp_path, tier="standard")
    result = runner.invoke(
        app,
        [
            "whatif",
            "--days",
            "1",
            "--tier",
            "standard",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "already at tier=standard" in result.output
    assert "no change" in result.output


def test_compare_warns_when_window_is_sparse(tmp_path) -> None:
    session_root, state_db, missing_cfg = _build_fixture(tmp_path, tier="standard")
    result = runner.invoke(
        app,
        [
            "compare",
            "--a",
            "last 1 days",
            "--b",
            "previous 1 days",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "not representative" in result.output
