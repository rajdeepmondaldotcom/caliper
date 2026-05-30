from __future__ import annotations

import datetime as dt
import json
import subprocess
import urllib.error
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from caliper import cli, health, prom_snapshot, rate_audit
from caliper.config import build_options
from caliper.health import check_rates_file, check_state_db_readable
from caliper.models import (
    LoadResult,
    RateLimitSample,
    ThreadMeta,
    Usage,
    UsageEvent,
)
from caliper.output import records_to_csv, records_to_markdown
from caliper.pricing import RateCard
from caliper.rate_audit import dedupe_models, extract_models_from_text, fetch_rate_sources

runner = CliRunner()


def _event(
    when: dt.datetime | None = None,
    *,
    model: str = "gpt-5.5",
    tier: str = "standard",
    total: int = 1500,
    usage: Usage | None = None,
    vendor: str = "openai-codex",
    model_source: str = "turn_context",
) -> UsageEvent:
    timestamp = when or dt.datetime.now(tz=dt.UTC)
    return UsageEvent(
        timestamp=timestamp,
        path=Path("rollout.jsonl"),
        session_id="session-1",
        usage=usage
        or Usage(
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
        model_source=model_source,
        vendor=vendor,
    )


def _result(
    *events: UsageEvent,
    rate_limit_samples: list[RateLimitSample] | None = None,
) -> LoadResult:
    return LoadResult(
        events=list(events),
        duplicates=0,
        tier_sources={"logged": len(events)},
        plan_types=set(),
        rate_limit_samples=rate_limit_samples or [],
        warnings=[],
    )


def test_records_helpers_handle_empty_and_escaping() -> None:
    assert records_to_csv([]) == ""
    assert records_to_markdown([]) == "_No data._\n"
    text = records_to_markdown([{"name": "a|b", "count": 2}])
    assert "a\\|b" in text
    assert "12.35" in records_to_csv([{"cache_pct": 12.34567}])
    assert "12.35" in records_to_markdown([{"cache_pct": 12.34567}])


def test_vendors_defaults_to_list_json() -> None:
    result = runner.invoke(cli.app, ["vendors", "--output-format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "vendors" in payload
    assert {row["id"] for row in payload["vendors"]} >= {"openai-codex", "claude-code"}


def test_version_label_survives_missing_git(monkeypatch) -> None:
    def fail_run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fail_run)
    assert "rates checked" in cli._version_label()


def test_fetch_rate_sources_records_network_errors(monkeypatch) -> None:
    def fail_urlopen(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    payload = fetch_rate_sources()
    assert payload["models"] == []
    assert {source["status"] for source in payload["sources"]} == {"error"}


def test_fetch_rate_sources_rejects_invalid_urls(monkeypatch) -> None:
    monkeypatch.setattr(
        rate_audit,
        "PRICING_SOURCES",
        [SimpleNamespace(name="bad source", url="file:///tmp/rates.json", checked="2026-05-12")],
    )

    payload = fetch_rate_sources()

    assert payload["models"] == []
    assert payload["sources"][0]["status"] == "error"
    assert "unsupported rate source URL" in payload["sources"][0]["error"]


def test_fetch_rate_sources_success_and_discrepancies(monkeypatch) -> None:
    body = json.dumps(
        {
            "models": [
                {
                    "name": "gpt-5.5",
                    "api": {"input": 999, "cached_input": 0.5, "output": 30},
                    "long_context": {
                        "threshold": 128000,
                        "input_mult": 2,
                        "output_mult": 1.25,
                    },
                }
            ]
        }
    ).encode()

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        rate_audit,
        "PRICING_SOURCES",
        [SimpleNamespace(name="unit source", url="https://example.test/rates.json", checked="now")],
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda _request, timeout: Response(body))

    payload = fetch_rate_sources()

    assert payload["sources"][0]["status"] == "ok"
    assert payload["observed_models"][0]["source"] == "unit source"
    sections = {item["section"] for item in payload["discrepancies"]}
    assert {"api", "long_context"} <= sections


def test_network_imports_stay_in_single_chokepoint() -> None:
    root = Path("src/caliper")
    offenders = [
        str(path)
        for path in root.rglob("*.py")
        if path.name != "network.py"
        and (
            "import urllib" in path.read_text()
            or "import http.client" in path.read_text()
            or "import socket" in path.read_text()
            or "import requests" in path.read_text()
            or "import httpx" in path.read_text()
            or "import aiohttp" in path.read_text()
        )
    ]

    assert offenders == []


def test_extract_and_dedupe_models() -> None:
    assert extract_models_from_text("not json") == []
    assert extract_models_from_text(json.dumps({"models": [{"name": "gpt-test"}]})) == [
        {"name": "gpt-test"}
    ]
    html = """
    <h1>GPT-5.1-Codex-Max</h1>
    <p>Pricing Text tokens Per 1M tokens Input $1.25 Cached input $0.125 Output $10.00</p>
    """
    assert extract_models_from_text(html) == [
        {
            "name": "gpt-5.1-codex-max",
            "api": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
        }
    ]
    assert dedupe_models([{"name": "b"}, {"name": "a"}, {"name": "b", "x": 1}]) == [
        {"name": "a"},
        {"name": "b", "x": 1},
    ]
    assert dedupe_models(
        [
            {"name": "gpt-5.5", "source": "a", "x": 1},
            {"name": "gpt-5.5", "source": "b", "y": 2},
        ]
    ) == [{"name": "gpt-5.5", "source": "a; b", "x": 1, "y": 2}]
    long_context_html = """
    <h1>GPT-5.4</h1>
    <p>For GPT-5.4, prompts with &gt;272K input tokens are priced at 2x input and
    1.5x output for the full session.</p>
    """
    long_models = extract_models_from_text(long_context_html)
    assert long_models == [
        {
            "name": "gpt-5.4",
            "long_context": {"threshold": 272_000, "input_mult": 2.0, "output_mult": 1.5},
        }
    ]


def test_check_state_db_readable_reports_missing(tmp_path) -> None:
    check = check_state_db_readable(tmp_path / "missing.sqlite")
    assert check.label == "State DB readable"
    assert check.status == "warn"
    assert "missing" in check.detail


def test_check_rates_file_reports_invalid(tmp_path) -> None:
    path = tmp_path / "rates.json"
    path.write_text("{")
    check = check_rates_file(path)
    assert check.label == "Rates file"
    assert check.status == "fail"
    assert "Could not read rates file" in check.detail


def test_health_checks_cover_warning_and_ok_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        health.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    assert health.check_codex_cli_version().status == "warn"

    def timeout_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("codex", 2)

    monkeypatch.setattr(health.subprocess, "run", timeout_run)
    assert "could not invoke" in health.check_codex_cli_version().detail

    assert "in the future" in health.clock_skew_detail(90)
    assert (
        health.check_clock_skew([_event(dt.datetime.now(tz=dt.UTC) + dt.timedelta(days=2))]).status
        == "fail"
    )
    assert (
        health.check_clock_skew([_event(dt.datetime.now(tz=dt.UTC) + dt.timedelta(hours=1))]).status
        == "warn"
    )

    state_db = tmp_path / "state.sqlite"
    state_db.write_text("not sqlite")
    assert health.check_state_db_readable(state_db).status == "warn"

    options = build_options(days=7)
    monkeypatch.setattr(health, "load_rate_card", lambda _options: RateCard.load(None, "model"))
    catalog_check = health.check_pricing_catalog(options)
    assert catalog_check.status == "ok"
    assert "offline mode" in catalog_check.detail
    assert health.check_cache_creation_rates([], options).status == "ok"
    missing_rate_event = _event(
        model="unknown-model",
        usage=Usage(input_tokens=10, cache_creation_input_tokens=5, total_tokens=10),
    )
    assert health.check_cache_creation_rates([missing_rate_event], options).status == "warn"
    explicit_rate_event = _event(
        model="claude-sonnet-4.6",
        usage=Usage(input_tokens=10, cache_creation_input_tokens=5, total_tokens=10),
    )
    assert health.check_cache_creation_rates([explicit_rate_event], options).status == "ok"


def test_pricing_catalog_doctor_warns_for_stale_offline_catalog(monkeypatch) -> None:
    options = build_options(days=7, offline=True)
    stale_card = RateCard.load(None, "model")
    monkeypatch.setattr(
        health,
        "pricing_catalog_status",
        lambda _card: {
            "source": "auto",
            "models": 1200,
            "age_hours": 24 * 30,
            "warnings": ["pricing catalog refresh failed: unit"],
        },
    )
    monkeypatch.setattr(health, "load_rate_card", lambda _options: stale_card)

    check = health.check_pricing_catalog(options)

    assert check.status == "warn"
    assert "1200" in check.detail.replace(",", "")


def test_build_health_report_surfaces_inferred_tiers_and_parser_warnings(tmp_path) -> None:
    options = build_options(
        days=7,
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    event = _event()
    result = LoadResult(
        events=[event],
        duplicates=0,
        tier_sources={"current-config": 1},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=["fixture warning"],
    )

    checks = health.build_health_report(options=options, session_file_count=1, result=result)
    by_label = {check.label: check for check in checks}

    assert by_label["Events loaded"].status == "ok"
    assert by_label["Tier coverage"].status == "warn"
    assert by_label["Parser warning"].detail == "fixture warning"


def test_options_wraps_value_error() -> None:
    with pytest.raises(cli.typer.Exit) as exc_info:
        cli._options({"days": -1})
    assert exc_info.value.exit_code == 2


def test_advisor_table_format_helpers_are_human_readable() -> None:
    assert cli._advisor_int(1315) == "1,315"
    assert cli._advisor_confidence(0.8) == "80%"
    assert cli._advisor_savings({"estimated_savings_usd_exact": "1315.3240317"}) == "$1,315.32"
    assert cli._advisor_savings({"estimated_savings_usd_exact": "0"}) == "-"


def test_tail_helpers_cover_event_and_session_rows() -> None:
    newest = _event(dt.datetime(2026, 5, 12, tzinfo=dt.UTC), total=2000)
    older = _event(dt.datetime(2026, 5, 11, tzinfo=dt.UTC), total=1000)
    rows = cli._recent_tail_rows(_result(older, newest), 1, "event")
    assert rows[0]["total_tokens"] == 2000
    assert rows[0]["session"] == "12:00 am, Tuesday 12 May 2026"

    session_rows = cli._recent_tail_rows(_result(older, newest), 1, "session")
    assert session_rows[0]["label"] == "12:00 am, Tuesday 12 May 2026 | Session One"
    assert "total_tokens" in cli._tail_csv(rows)

    options = build_options(days=7)
    table = cli._tail_table(rows, "event", options)
    assert "Recent Events" in table
    assert "Tuesday 12 May 2026" in table


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
    assert "cost_usd" in csv_result.output

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
    assert "cost_usd" in csv_result.output

    markdown_result = runner.invoke(cli.app, [*base_args, "--format", "markdown"])
    assert markdown_result.exit_code == 0, markdown_result.output
    assert "| metric |" in markdown_result.output

    table_result = runner.invoke(cli.app, base_args)
    assert table_result.exit_code == 0, table_result.output
    assert "What If" in table_result.output


def test_budgets_check_formats_and_table(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "load_usage", lambda _options: _result(_event()))
    config = tmp_path / ".caliper.toml"
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
    assert "Caliper - Budgets" in table_result.output

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
    monkeypatch.setattr(prom_snapshot, "local_timezone", lambda: dt.UTC)
    now = dt.datetime.now(tz=dt.UTC)
    sample = RateLimitSample(
        timestamp=now,
        path=Path("rollout.jsonl"),
        session_id="session-1",
        primary_used_percent=12.5,
        secondary_used_percent=3.5,
    )
    load_result = _result(_event(now), rate_limit_samples=[sample])
    monkeypatch.setattr(prom_snapshot, "load_usage", lambda _options: load_result)

    options = build_options(
        days=7,
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    snapshot = prom_snapshot.build_prometheus_snapshot(options)

    assert snapshot.events_total == 1
    assert snapshot.primary_window_percent == 12.5
    assert snapshot.tokens_total[("gpt-5.5", "standard", "input")] == 1000
