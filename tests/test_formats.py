from __future__ import annotations

import csv
import datetime as dt
import io
import json

from typer.testing import CliRunner

from caliper.cli import app

from .conftest import make_state_db, rate_limit_only_event, token_event, turn_context, write_session

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


def test_daily_table_loudly_announces_vendors(tmp_path) -> None:
    """Every table report announces which vendors contributed events."""
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
            "--vendor",
            "openai-codex",
        ]
    )
    assert result.exit_code == 0, result.output
    assert "Vendors: openai-codex" in result.output
    assert "events" in result.output


def test_daily_json_carries_vendor_event_counts(tmp_path) -> None:
    """The JSON payload exposes per-vendor event counts under metadata."""
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
            "--vendor",
            "openai-codex",
        ]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    counts = payload["metadata"]["vendor_event_counts"]
    assert isinstance(counts, dict)
    assert counts.get("openai-codex", 0) >= 1


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
        "caliper",
        "command",
        "generated_at",
        "window",
        "totals",
        "breakdowns",
        "projects",
        "model_mode",
        "pricing",
        "subscription",
        "metadata",
        "rate_limit_samples",
        "warnings",
    }
    assert payload["caliper"]["schema_version"] == 2
    assert isinstance(payload["rate_limit_samples"], list)
    assert payload["command"] == "daily"
    assert payload["totals"]["input_tokens"] == 1000
    assert payload["totals"]["cached_input_tokens"] == 500
    assert payload["totals"]["output_tokens"] == 100
    assert payload["totals"]["reasoning_output_tokens"] == 25
    assert payload["totals"]["total_tokens"] == 1100
    assert payload["totals"]["cache_savings_cost_usd"] > 0
    assert payload["totals"]["cache_savings_cost_usd"] > 0
    assert payload["totals"]["events"] == 1
    assert payload["totals"]["models"] == ["gpt-5.5"]
    assert payload["totals"]["service_tiers"] == ["standard"]
    assert payload["totals"]["model_sources"] == ["turn_context"]
    assert payload["totals"]["fallback_model_events"] == 0
    assert payload["totals"]["model_breakdowns"][0]["model"] == "gpt-5.5"
    assert payload["totals"]["model_breakdowns"][0]["service_tier"] == "standard"
    assert payload["totals"]["model_breakdowns"][0]["events"] == 1
    assert payload["totals"]["model_breakdowns"][0]["model_sources"] == ["turn_context"]
    assert payload["totals"]["model_breakdowns"][0]["cost_usd_exact"]
    assert payload["totals"]["subscription_plans"][0]["slug"] == "pro"
    assert payload["pricing"]["mode"] == "model"
    assert payload["subscription"]["plans"][0]["slug"] == "pro"
    assert payload["metadata"]["tier_sources"] == {"logged": 1}
    assert payload["metadata"]["model_sources"] == {"turn_context": 1}
    assert payload["metadata"]["plan_types"] == ["pro"]
    assert payload["metadata"]["path_redaction"] == "redacted"
    assert payload["metadata"]["workspace_coverage"] == {
        "events": 1,
        "events_with_project": 1,
        "event_coverage": 1.0,
        "sessions": 1,
        "sessions_with_project": 1,
        "session_coverage": 1.0,
        "project_count": 1,
    }
    assert payload["metadata"]["evidence"]["dimensions"]
    assert any(
        row["vendor"] == "openai-codex"
        for row in payload["metadata"]["evidence"]["vendor_coverage"]
    )
    assert len(payload["breakdowns"]) == 1
    assert len(payload["projects"]) == 1
    assert payload["projects"][0]["session_count"] == 1
    assert payload["projects"][0]["project_paths"] == ["<redacted-path>"]
    assert payload["projects"][0]["project_names"] == ["project-alpha"]
    assert payload["projects"][0]["git_origins"] == ["<redacted-repo>"]
    assert payload["projects"][0]["git_branches"] == ["<redacted-git-branch>"]
    assert payload["projects"][0]["model_breakdowns"][0]["model"] == "gpt-5.5"
    assert payload["projects"][0]["first_seen"]
    assert payload["projects"][0]["last_seen"]


def test_grouped_json_bounds_rate_limit_samples_by_default(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-samples.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(now, {"input_tokens": 100, "output_tokens": 1, "total_tokens": 101}),
            token_event(
                now + dt.timedelta(seconds=1),
                {"input_tokens": 200, "output_tokens": 2, "total_tokens": 202},
            ),
            token_event(
                now + dt.timedelta(seconds=2),
                {"input_tokens": 300, "output_tokens": 3, "total_tokens": 303},
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    common_args = [
        "daily",
        "--days",
        "1",
        "--until",
        (now + dt.timedelta(minutes=1)).isoformat(),
        "--session-root",
        str(session_root),
        "--state-db",
        str(state_db),
        "--codex-config",
        str(tmp_path / "missing.toml"),
        "--format",
        "json",
        "--vendor",
        "openai-codex",
    ]

    limited = _invoke([*common_args, "--rate-limit-sample-limit", "2"])
    assert limited.exit_code == 0, limited.output
    limited_payload = json.loads(limited.output)
    assert len(limited_payload["rate_limit_samples"]) == 2
    assert limited_payload["metadata"]["rate_limit_sample_count"] == 3
    assert limited_payload["metadata"]["rate_limit_sample_limit"] == 2
    assert limited_payload["metadata"]["rate_limit_samples_truncated"] is True

    exhaustive = _invoke([*common_args, "--include-all-rate-limit-samples"])
    assert exhaustive.exit_code == 0, exhaustive.output
    exhaustive_payload = json.loads(exhaustive.output)
    assert len(exhaustive_payload["rate_limit_samples"]) == 3
    assert exhaustive_payload["metadata"]["rate_limit_sample_limit"] is None
    assert exhaustive_payload["metadata"]["rate_limit_samples_truncated"] is False


def test_grouped_json_reports_rate_limit_sample_dedupe(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    sample = rate_limit_only_event(now)
    write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-dupe-samples.jsonl",
        [sample, sample],
    )
    result = _invoke(
        [
            "daily",
            "--days",
            "1",
            "--until",
            (now + dt.timedelta(minutes=1)).isoformat(),
            "--session-root",
            str(session_root),
            "--state-db",
            str(tmp_path / "missing.sqlite"),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "--format",
            "json",
            "--vendor",
            "openai-codex",
        ]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert len(payload["rate_limit_samples"]) == 1
    assert payload["metadata"]["rate_limit_sample_count"] == 1
    assert payload["metadata"]["dedupe"]["rate_limit_sample_duplicates"] == 1
    assert payload["metadata"]["dedupe"]["rate_limit_samples_by_strategy"] == {
        "rate_limit_sample": 1
    }


def test_table_warns_when_model_has_unpriced_costs(tmp_path) -> None:
    session_root, state_db, until, missing_cfg = _fixture(tmp_path, model="future-model")
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
    assert "unpriced" in result.output
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
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_1h_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
        "cost_usd",
        "reported_cost_usd",
        "calculated_cost_usd",
        "reported_minus_calculated_cost_usd",
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
    assert "Cost $" in lines[0]
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
    assert "Caliper - Daily" in result.output
    assert "Window:" in result.output
    assert "gpt-5.5" in result.output
    assert "1,100" in result.output
    assert "Total" in result.output
    assert "Cache discount:" in result.output


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


def test_project_json_exposes_workspace_provenance(tmp_path) -> None:
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
            "--show-paths",
            "--format",
            "json",
        ]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    project = payload["breakdowns"][0]

    assert project["label"] == "/tmp/project-alpha"
    assert project["session_count"] == 1
    assert project["sessions"]
    assert project["project_paths"] == ["/tmp/project-alpha"]
    assert project["project_names"] == ["project-alpha"]
    assert project["git_origins"] == ["https://github.com/example/project-alpha"]
    assert project["first_seen"] == project["last_seen"]


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
    assert round(payload["totals"]["cost_usd"], 2) == 3.45


def test_daily_json_fast_tier_has_same_usd_cost(tmp_path) -> None:
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
    standard = payload["totals"]["calculated_cost_usd"]
    adjusted = payload["totals"]["cost_usd"]
    assert adjusted == standard
