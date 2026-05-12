from __future__ import annotations

import json

from typer.testing import CliRunner

from codex_meter.cli import app
from codex_meter.prom_export import MetricsSnapshot, build_metrics_text

runner = CliRunner()


def test_metrics_text_includes_all_expected_metric_names() -> None:
    snapshot = MetricsSnapshot(
        credits_used=123.45,
        burn_per_hour=10.5,
        primary_window_percent=42.0,
        secondary_window_percent=8.0,
        events_total=12,
        long_context_events_total=2,
        tokens_total={
            ("gpt-5.5", "fast", "input"): 1000,
            ("gpt-5.5", "fast", "output"): 200,
        },
    )
    body = build_metrics_text(snapshot).decode()
    for metric in (
        "codex_meter_credits_used",
        "codex_meter_burn_per_hour",
        "codex_meter_window_used_percent",
        "codex_meter_tokens_total",
        "codex_meter_events_total",
        "codex_meter_long_context_events_total",
    ):
        assert metric in body
    assert 'window="primary"' in body
    assert 'window="secondary"' in body
    assert 'model="gpt-5.5"' in body
    assert 'kind="output"' in body


def test_metrics_text_handles_empty_tokens_dict() -> None:
    snapshot = MetricsSnapshot(
        credits_used=0.0,
        burn_per_hour=0.0,
        primary_window_percent=0.0,
        secondary_window_percent=0.0,
        events_total=0,
        long_context_events_total=0,
    )
    body = build_metrics_text(snapshot).decode()
    assert "codex_meter_credits_used 0.0" in body


def test_export_grafana_cli_emits_valid_dashboard_json() -> None:
    result = runner.invoke(app, ["export", "grafana"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["title"] == "Codex Meter"
    assert {panel["type"] for panel in parsed["panels"]} >= {"stat", "gauge", "timeseries"}


def test_export_receipt_cli_renders_markdown(tmp_path) -> None:
    import datetime as dt

    from .conftest import make_state_db, token_event, turn_context, write_session

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
                    "reasoning_output_tokens": 25,
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
            "export",
            "receipt",
            "--month",
            now.strftime("%Y-%m"),
            "--format",
            "markdown",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "# Codex Meter Receipt" in result.output
    assert "## Totals" in result.output


def test_export_receipt_rejects_bad_month() -> None:
    result = runner.invoke(app, ["export", "receipt", "--month", "potato"])
    assert result.exit_code == 2
    assert "YYYY-MM" in result.output


def test_export_receipt_rejects_bad_format() -> None:
    result = runner.invoke(app, ["export", "receipt", "--format", "pdf"])
    assert result.exit_code == 2
    assert "markdown, html" in result.output
