from __future__ import annotations

import datetime as dt
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codex_meter import cli
from codex_meter.config import build_options
from codex_meter.models import LoadResult, RateLimitSample, ThreadMeta, Usage, UsageEvent

runner = CliRunner()


def _event(
    when: dt.datetime | None = None,
    *,
    model: str = "gpt-5.5",
    tier: str = "standard",
    total: int = 1500,
) -> UsageEvent:
    timestamp = when or dt.datetime.now(tz=dt.UTC)
    return UsageEvent(
        timestamp=timestamp,
        path=Path("rollout.jsonl"),
        session_id="session-1",
        usage=Usage(
            input_tokens=1000,
            cached_input_tokens=100,
            output_tokens=300,
            reasoning_output_tokens=200,
            total_tokens=total,
        ),
        model=model,
        service_tier=tier,
        tier_source="logged",
        thread=ThreadMeta(title="Session One", cwd="/repo"),
    )


def _result(
    *events: UsageEvent,
    credit_samples: list[RateLimitSample] | None = None,
) -> LoadResult:
    return LoadResult(
        events=list(events),
        duplicates=0,
        tier_sources={"logged": len(events)},
        plan_types=set(),
        credit_samples=credit_samples or [],
        warnings=[],
    )


def test_records_helpers_handle_empty_and_escaping() -> None:
    assert cli._records_to_csv([]) == ""
    assert cli._records_to_markdown([]) == "_No data._\n"
    text = cli._records_to_markdown([{"name": "a|b", "count": 2}])
    assert "a\\|b" in text


def test_version_label_survives_missing_git(monkeypatch) -> None:
    def fail_run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fail_run)
    assert "rates checked" in cli._version_label()


def test_fetch_rate_sources_records_network_errors(monkeypatch) -> None:
    def fail_urlopen(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    payload = cli._fetch_rate_sources()
    assert payload["models"] == []
    assert {source["status"] for source in payload["sources"]} == {"error"}


def test_extract_and_dedupe_models() -> None:
    assert cli._extract_models_from_text("not json") == []
    assert cli._extract_models_from_text(json.dumps({"models": [{"name": "gpt-test"}]})) == [
        {"name": "gpt-test"}
    ]
    html = """
    <h1>GPT-5.1-Codex-Max</h1>
    <p>Pricing Text tokens Per 1M tokens Input $1.25 Cached input $0.125 Output $10.00</p>
    """
    assert cli._extract_models_from_text(html) == [
        {
            "name": "gpt-5.1-codex-max",
            "api": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
        }
    ]
    assert cli._dedupe_models([{"name": "b"}, {"name": "a"}, {"name": "b", "x": 1}]) == [
        {"name": "a"},
        {"name": "b", "x": 1},
    ]
    speed_html = """
    <p>Fast mode consumes credits at 2.5x the Standard rate for GPT-5.5 and
    2x the Standard rate for GPT-5.4.</p>
    """
    speed_models = cli._extract_models_from_text(speed_html)
    assert (
        next(model for model in speed_models if model["name"] == "gpt-5.5")["fast_multiplier"]
        == 2.5
    )
    assert (
        next(model for model in speed_models if model["name"] == "gpt-5.4")["fast_multiplier"]
        == 2.0
    )
    long_context_html = """
    <h1>GPT-5.4</h1>
    <p>For GPT-5.4, prompts with &gt;272K input tokens are priced at 2x input and
    1.5x output for the full session.</p>
    """
    long_models = cli._extract_models_from_text(long_context_html)
    assert long_models == [
        {
            "name": "gpt-5.4",
            "long_context": {"threshold": 272_000, "input_mult": 2.0, "output_mult": 1.5},
        }
    ]


def test_check_state_db_readable_reports_missing(tmp_path) -> None:
    label, status, detail = cli._check_state_db_readable(tmp_path / "missing.sqlite")
    assert label == "State DB readable"
    assert status == "warn"
    assert "missing" in detail


def test_check_rates_file_reports_invalid(tmp_path) -> None:
    path = tmp_path / "rates.json"
    path.write_text("{")
    label, status, detail = cli._check_rates_file(path)
    assert label == "Rates file"
    assert status == "fail"
    assert "Could not read rates file" in detail


def test_options_wraps_value_error() -> None:
    with pytest.raises(cli.typer.Exit) as exc_info:
        cli._options({"days": -1})
    assert exc_info.value.exit_code == 2


def test_tail_helpers_cover_event_and_session_rows() -> None:
    newest = _event(dt.datetime(2026, 5, 12, tzinfo=dt.UTC), total=2000)
    older = _event(dt.datetime(2026, 5, 11, tzinfo=dt.UTC), total=1000)
    rows = cli._recent_tail_rows(_result(older, newest), 1, "event")
    assert rows[0]["total_tokens"] == 2000

    session_rows = cli._recent_tail_rows(_result(older, newest), 1, "session")
    assert session_rows[0]["label"] == "Session One"
    assert "total_tokens" in cli._tail_csv(rows)

    options = build_options(days=7)
    table = cli._tail_table(rows, "event", options)
    assert "Recent Events" in table


def test_forecast_csv_and_markdown_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "load_usage", lambda _options: _result(_event()))
    base_args = [
        "forecast",
        "--session-root",
        str(tmp_path / "sessions"),
        "--state-db",
        str(tmp_path / "state.sqlite"),
        "--codex-config",
        str(tmp_path / "missing.toml"),
    ]

    csv_result = runner.invoke(cli.app, [*base_args, "--format", "csv"])
    assert csv_result.exit_code == 0, csv_result.output
    assert "api_dollars" in csv_result.output

    markdown_result = runner.invoke(cli.app, [*base_args, "--format", "markdown"])
    assert markdown_result.exit_code == 0, markdown_result.output
    assert "| unit |" in markdown_result.output


def test_whatif_non_noop_csv_markdown_and_table(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "load_usage", lambda _options: _result(_event(tier="standard")))
    base_args = [
        "whatif",
        "--tier",
        "fast",
        "--session-root",
        str(tmp_path / "sessions"),
        "--state-db",
        str(tmp_path / "state.sqlite"),
        "--codex-config",
        str(tmp_path / "missing.toml"),
    ]

    csv_result = runner.invoke(cli.app, [*base_args, "--format", "csv"])
    assert csv_result.exit_code == 0, csv_result.output
    assert "api_dollars" in csv_result.output

    markdown_result = runner.invoke(cli.app, [*base_args, "--format", "markdown"])
    assert markdown_result.exit_code == 0, markdown_result.output
    assert "| metric |" in markdown_result.output

    table_result = runner.invoke(cli.app, base_args)
    assert table_result.exit_code == 0, table_result.output
    assert "What If" in table_result.output


def test_budgets_check_formats_and_table(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "load_usage", lambda _options: _result(_event()))
    config = tmp_path / ".codex-meter.toml"
    config.write_text("[budgets]\ndaily_tokens = 1_000_000\n")
    base_args = [
        "budgets",
        "check",
        "--config",
        str(config),
        "--session-root",
        str(tmp_path / "sessions"),
        "--state-db",
        str(tmp_path / "state.sqlite"),
        "--codex-config",
        str(tmp_path / "missing.toml"),
    ]

    table_result = runner.invoke(cli.app, base_args)
    assert table_result.exit_code == 0, table_result.output
    assert "Codex Meter - Budgets" in table_result.output

    json_result = runner.invoke(cli.app, [*base_args, "--format", "json"])
    assert json_result.exit_code == 0, json_result.output
    json_payload = json.loads(json_result.output)
    assert json_payload["max_severity"] == "ok"
    assert "used_exact" in json_payload["alerts"][0]

    csv_result = runner.invoke(cli.app, [*base_args, "--format", "csv"])
    assert csv_result.exit_code == 0, csv_result.output
    assert "period,metric,limit" in csv_result.output

    markdown_result = runner.invoke(cli.app, [*base_args, "--format", "markdown"])
    assert markdown_result.exit_code == 0, markdown_result.output
    assert "| period | metric | limit |" in markdown_result.output


def test_prometheus_snapshot_aggregates_today(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "local_timezone", lambda: dt.UTC)
    now = dt.datetime.now(tz=dt.UTC)
    sample = RateLimitSample(
        timestamp=now,
        path=Path("rollout.jsonl"),
        session_id="session-1",
        primary_used_percent=12.5,
        secondary_used_percent=3.5,
    )
    load_result = _result(_event(now), credit_samples=[sample])
    monkeypatch.setattr(cli, "load_usage", lambda _options: load_result)

    options = build_options(
        days=7,
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    snapshot = cli._build_prometheus_snapshot(options)

    assert snapshot.events_total == 1
    assert snapshot.primary_window_percent == 12.5
    assert snapshot.tokens_total[("gpt-5.5", "standard", "input")] == 1000
