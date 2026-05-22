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
    assert "Caliper - Forecast" in result.output
    assert "Daily mean" in result.output
    assert "$0.00" in result.output
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
    assert "cost_usd" in payload["projections"]
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


def test_whatif_tier_swap_reduces_cost_usd_when_going_from_fast_to_standard(tmp_path) -> None:
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
    assert payload["actual"]["cost_usd"] > payload["projected"]["cost_usd"]
    assert "cost_usd_exact" in payload["actual"]
    assert "cost_usd_exact" in payload["projected"]
    assert payload["delta"]["cost_usd"] < 0
    assert "cost_usd_exact" in payload["delta"]


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


def test_whatif_accepts_latest_family_aliases(tmp_path) -> None:
    session_root, state_db, missing_cfg = _build_fixture(tmp_path)
    result = runner.invoke(
        app,
        [
            "whatif",
            "--days",
            "1",
            "--model",
            "claude-3-haiku",
            "--tier",
            "xhigh",
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
    assert payload["hypothetical"] == {"tier": "fast", "model": "claude-haiku-4.5"}


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
    assert payload["a"]["cost_usd"] >= 0
    assert "cost_usd_exact" in payload["a"]
    assert payload["b"]["cost_usd"] >= 0
    assert "cost_usd_exact" in payload["delta"]
    assert payload["delta"]["cost_usd_pct"] is None
    assert payload["delta"]["tokens_pct"] is None


def test_compare_markdown_uses_human_money_and_zero_baseline_na(tmp_path) -> None:
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
            "markdown",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "| cost_usd | $" in result.output
    assert "n/a" in result.output
    assert "1,100" in result.output
    assert "Decimal(" not in result.output


def test_whatif_markdown_uses_human_money_and_percent_format(tmp_path) -> None:
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
            "markdown",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "| cost_usd | $" in result.output
    assert "%" in result.output
    assert "Decimal(" not in result.output


def test_compare_by_vendor_breaks_out_each_vendor(tmp_path) -> None:
    """`caliper compare --by vendor --format json` yields a by_vendor array."""
    session_root, state_db, missing_cfg = _build_fixture(tmp_path, tier="standard")
    result = runner.invoke(
        app,
        [
            "compare",
            "--a",
            "last 1 days",
            "--b",
            "previous 1 days",
            "--by",
            "vendor",
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
    assert "by_vendor" in payload
    assert isinstance(payload["by_vendor"], list)
    assert any(row.get("vendor") == "openai-codex" for row in payload["by_vendor"])


def test_compare_by_vendor_table_renders_vendor_column(tmp_path) -> None:
    """The default table for `--by vendor` carries a Vendor column."""
    session_root, state_db, missing_cfg = _build_fixture(tmp_path, tier="standard")
    result = runner.invoke(
        app,
        [
            "compare",
            "--a",
            "last 1 days",
            "--b",
            "previous 1 days",
            "--by",
            "vendor",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Compare by vendor" in result.output
    assert "Vendor" in result.output
    # Vendor id may wrap across table cells; substring is enough to prove presence.
    assert "openai" in result.output


def test_compare_rejects_unknown_by_value(tmp_path) -> None:
    """`--by` only accepts total or vendor."""
    session_root, state_db, missing_cfg = _build_fixture(tmp_path, tier="standard")
    result = runner.invoke(
        app,
        [
            "compare",
            "--by",
            "garbage",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code == 2
    assert "--by must be one of: total, vendor" in result.output


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
    assert "n/a" in result.output
