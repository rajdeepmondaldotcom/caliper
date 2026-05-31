from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from caliper import SCHEMA_VERSION, __version__
from caliper.cli import app
from caliper.timeutil import local_timezone

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _fixture(tmp_path: Path, *, tier: str = "fast") -> tuple[Path, Path, str, Path, Path]:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-surface.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier=tier),
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 600,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    if state_db.exists():
        state_db.unlink()
    make_state_db(state_db, session_path)
    config = tmp_path / ".caliper.toml"
    config.write_text("[budgets]\ndaily_cost_usd = 1000000\n")
    return (
        session_root,
        state_db,
        (now + dt.timedelta(seconds=1)).isoformat(),
        tmp_path / "missing.toml",
        config,
    )


def _data_args(tmp_path: Path, *, tier: str = "fast") -> list[str]:
    session_root, state_db, until, missing_cfg, _config = _fixture(tmp_path, tier=tier)
    return [
        "--days",
        "7",
        "--until",
        until,
        "--session-root",
        str(session_root),
        "--state-db",
        str(state_db),
        "--codex-config",
        str(missing_cfg),
    ]


def _source_args(tmp_path: Path, *, tier: str = "fast") -> list[str]:
    session_root, state_db, _until, missing_cfg, _config = _fixture(tmp_path, tier=tier)
    return [
        "--session-root",
        str(session_root),
        "--state-db",
        str(state_db),
        "--codex-config",
        str(missing_cfg),
    ]


def _args_for(tmp_path: Path, command: list[str], fmt: str) -> list[str]:
    if command[0] in {"taxonomy", "rates"}:
        return command + ["--format", fmt]
    if command[:2] == ["vendors", "list"]:
        return command + _source_args(tmp_path) + ["--format", fmt]
    if command[0] in {"forecast", "compare", "whatif"}:
        return command + _source_args(tmp_path) + ["--format", fmt]
    if command[0] == "advise" and "--explain" in command:
        return command + ["--format", fmt]
    return command + _data_args(tmp_path) + ["--format", fmt]


@pytest.mark.parametrize(
    ("command", "payload_key"),
    [
        (["insights"], "insights"),
        (["tail", "--n", "1"], "events"),
        (["taxonomy", "show"], "models"),
        (["vendors", "list"], "vendors"),
        (["rates", "show"], "models"),
        (["evidence"], "evidence"),
        (["forecast", "--days", "7"], "projections"),
        (["compare", "--a", "last 1 days", "--b", "previous 1 days"], "delta"),
        (
            ["compare", "--a", "last 1 days", "--b", "previous 1 days", "--by", "vendor"],
            "by_vendor",
        ),
        (["advise"], "records"),
        (["whatif", "--days", "1", "--tier", "standard"], "actual"),
        (["statusline"], "today"),
    ],
)
def test_cli_owned_json_outputs_carry_caliper_envelope(
    tmp_path: Path, command: list[str], payload_key: str
) -> None:
    result = runner.invoke(app, _args_for(tmp_path, command, "json"))

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[payload_key] is not None
    assert payload["caliper"] == {"version": __version__, "schema_version": SCHEMA_VERSION}


def test_budgets_json_output_carries_caliper_envelope(tmp_path: Path) -> None:
    session_root, state_db, _until, missing_cfg, config = _fixture(tmp_path)
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
            str(missing_cfg),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["alerts"]
    assert payload["caliper"] == {"version": __version__, "schema_version": SCHEMA_VERSION}


def test_specialized_commands_accept_shared_release_flags(tmp_path: Path) -> None:
    session_root, state_db, until, missing_cfg, config = _fixture(tmp_path)
    shared = [
        "--session-root",
        str(session_root),
        "--state-db",
        str(state_db),
        "--codex-config",
        str(missing_cfg),
    ]

    cases = [
        ["whatif", "--days", "1", "--tier", "standard", *shared, "--no-cache"],
        ["advise", "--days", "7", "--until", until, *shared, "--width", "100", "--no-cache"],
        [
            "budgets",
            "check",
            "--config",
            str(config),
            *shared,
            "--no-cache",
            "--format",
            "json",
        ],
    ]
    for args in cases:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    ("command", "fmt", "needle"),
    [
        (["insights"], "table", "Caliper - Insights"),
        (["insights"], "markdown", "| Severity | Insight |"),
        (["tail", "--n", "1", "--by", "session"], "csv", "label"),
        (["taxonomy", "show"], "table", "Model Taxonomy"),
        (["taxonomy", "show"], "csv", "canonical"),
        (["taxonomy", "show"], "markdown", "| vendor |"),
        (["vendors", "list"], "table", "Caliper - Vendors"),
        (["vendors", "list"], "csv", "openai-codex"),
        (["vendors", "list"], "markdown", "| id |"),
        (["rates", "show"], "table", "Caliper - Rate Card"),
        (["rates", "show"], "csv", "gpt-5.5"),
        (["rates", "show"], "markdown", "| model |"),
        (["evidence"], "table", "Caliper - Evidence"),
        (["evidence"], "csv", "dimension"),
        (["evidence"], "markdown", "| section |"),
        (["forecast", "--days", "7"], "csv", "cost_usd"),
        (["forecast", "--days", "7"], "markdown", "| unit |"),
        (["compare", "--a", "last 1 days", "--b", "previous 1 days"], "table", "Compare"),
        (["compare", "--a", "last 1 days", "--b", "previous 1 days"], "csv", "cost_usd"),
        (["compare", "--a", "last 1 days", "--b", "previous 1 days"], "markdown", "| metric |"),
        (
            ["compare", "--a", "last 1 days", "--b", "previous 1 days", "--by", "vendor"],
            "table",
            "Compare by vendor",
        ),
        (
            ["compare", "--a", "last 1 days", "--b", "previous 1 days", "--by", "vendor"],
            "csv",
            "openai-codex",
        ),
        (
            ["compare", "--a", "last 1 days", "--b", "previous 1 days", "--by", "vendor"],
            "markdown",
            "| vendor |",
        ),
        (["advise", "--explain", "premium-short-context"], "table", "Advisor Rule"),
        (["advise", "--explain", "premium-short-context"], "csv", "premium-short-context"),
        (["advise", "--explain", "premium-short-context"], "markdown", "| heuristics_version |"),
    ],
)
def test_cli_table_csv_and_markdown_branches(
    tmp_path: Path, command: list[str], fmt: str, needle: str
) -> None:
    result = runner.invoke(app, _args_for(tmp_path, command, fmt))

    assert result.exit_code == 0, result.output
    assert needle in result.output


def test_output_file_paths_are_used_for_command_owned_outputs(tmp_path: Path) -> None:
    insights_out = tmp_path / "insights.json"
    result = runner.invoke(
        app,
        ["insights", *_data_args(tmp_path), "--format", "json", "--output", str(insights_out)],
    )
    assert result.exit_code == 0, result.output
    assert result.output == ""
    assert json.loads(insights_out.read_text())["caliper"]["schema_version"] == SCHEMA_VERSION

    grafana_out = tmp_path / "grafana.json"
    result = runner.invoke(
        app,
        ["export", "grafana", "--title", "Surface Test", "--output", str(grafana_out)],
    )
    assert result.exit_code == 0, result.output
    assert result.output == ""
    assert json.loads(grafana_out.read_text())["title"] == "Surface Test"


def test_export_receipt_cli_redacts_by_default_and_can_show_sensitive(tmp_path: Path) -> None:
    session_root, state_db, until, missing_cfg, _config = _fixture(tmp_path, tier="standard")
    event_at = dt.datetime.fromisoformat(until) - dt.timedelta(seconds=1)
    receipt_month = event_at.astimezone(local_timezone()).strftime("%Y-%m")
    base = [
        "--session-root",
        str(session_root),
        "--state-db",
        str(state_db),
        "--codex-config",
        str(missing_cfg),
    ]
    redacted = runner.invoke(
        app,
        ["export", "receipt", "--month", receipt_month, *base, "--format", "markdown"],
    )
    assert redacted.exit_code == 0, redacted.output
    assert "Session 1" in redacted.output
    assert "/tmp/project-alpha" not in redacted.output

    sensitive = runner.invoke(
        app,
        [
            "export",
            "receipt",
            "--month",
            receipt_month,
            *base,
            "--format",
            "html",
            "--show-sensitive",
        ],
    )
    assert sensitive.exit_code == 0, sensitive.output
    assert "<!doctype html>" in sensitive.output
    assert "/tmp/project-alpha" in sensitive.output


def test_command_validation_errors_cover_public_messages(tmp_path: Path) -> None:
    bad_insights = runner.invoke(app, ["insights", *_data_args(tmp_path), "--format", "csv"])
    assert bad_insights.exit_code == 2
    assert "table, json, markdown" in bad_insights.output

    bad_tail = runner.invoke(app, ["tail", "--by", "project", *_data_args(tmp_path)])
    assert bad_tail.exit_code == 2
    assert "event, session" in bad_tail.output

    bad_compare = runner.invoke(app, ["compare", "--by", "model", *_source_args(tmp_path)])
    assert bad_compare.exit_code == 2
    assert "total, vendor" in bad_compare.output

    bad_receipt = runner.invoke(app, ["export", "receipt", "--month", "2026-13"])
    assert bad_receipt.exit_code == 2
    assert "Month must be 1..12" in bad_receipt.output

    bad_explain = runner.invoke(app, ["advise", "--explain", "missing-rule"])
    assert bad_explain.exit_code == 2
    assert "unknown rule_id" in bad_explain.output
