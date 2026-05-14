"""Smoke tests for every command — exit 0 + key fields on a shared fixture."""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from caliper import cli
from caliper.cli import app
from caliper.models import Rates
from caliper.pricing_catalog import CatalogModel, PricingCatalog

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _build(tmp_path) -> tuple:
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
                    "total_tokens": 1100,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    state_db.unlink(missing_ok=True)
    make_state_db(state_db, session_path)
    return (
        session_root,
        state_db,
        (now + dt.timedelta(seconds=1)).isoformat(),
        tmp_path / "missing.toml",
    )


def _common_args(tmp_path) -> list:
    session_root, state_db, until, missing_cfg = _build(tmp_path)
    return [
        "--days",
        "30",
        "--until",
        until,
        "--session-root",
        str(session_root),
        "--state-db",
        str(state_db),
        "--codex-config",
        str(missing_cfg),
    ]


def _common_verbose_args(tmp_path) -> list:
    session_root, state_db, until, missing_cfg = _build(tmp_path)
    return [
        "--lookback-days",
        "30",
        "--window-end",
        until,
        "--codex-session-root",
        str(session_root),
        "--codex-state-db",
        str(state_db),
        "--codex-config-file",
        str(missing_cfg),
    ]


def test_default_overview_accepts_data_source_options(tmp_path) -> None:
    session_root, state_db, _until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
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
    assert payload["command"] == "overview"
    assert payload["totals"]["total_tokens"] == 1100


def test_overview_command_accepts_data_source_options(tmp_path) -> None:
    session_root, state_db, _until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "overview",
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
    assert payload["command"] == "overview"
    assert payload["totals"]["total_tokens"] == 1100


def test_overview_command_accepts_parent_output_options(tmp_path) -> None:
    session_root, state_db, _until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            "--vendor",
            "openai-codex",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "overview",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "overview"
    assert payload["metadata"]["vendor_event_counts"] == {"openai-codex": 1}


def test_weekly_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["weekly", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "weekly"
    assert payload["totals"]["total_tokens"] == 1100


def test_monthly_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["monthly", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "monthly"
    assert payload["totals"]["total_tokens"] == 1100


def test_session_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["session", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "session"
    assert payload["totals"]["total_tokens"] == 1100
    assert len(payload["breakdowns"]) == 1


def test_daily_compat_json_shape(tmp_path) -> None:
    result = runner.invoke(app, ["daily", *_common_args(tmp_path), "--format", "compat-json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["totalTokens"] == 1100
    assert payload["daily"][0]["modelsUsed"] == ["gpt-5.5"]


def test_compat_flag_names_are_not_caliper_aliases(tmp_path) -> None:
    common_args = _common_args(tmp_path)
    for flag in ("--json", "--mode", "-O", "--locale", "--color", "--no-color"):
        args = ["daily", *common_args, flag]
        if flag in {"--mode", "--locale"}:
            args.append("calculate" if flag == "--mode" else "en-US")

        result = runner.invoke(app, args)

        assert result.exit_code == 2, flag
        assert "No such option" in result.output


def test_caliper_differentiated_flags_cover_same_work(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "daily",
            *_common_args(tmp_path),
            "--format",
            "compat-json",
            "--cost-mode",
            "calculate",
            "--offline",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["daily"]
    assert payload["totals"]["totalTokens"] == 1100


def test_verbose_report_flags_cover_same_work(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "daily",
            *_common_verbose_args(tmp_path),
            "--output-format",
            "compat-json",
            "--vendor-cost-mode",
            "calculate",
            "--pricing-offline-only",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["daily"][0]["totalTokens"] == 1100


def test_verbose_session_and_block_flags_cover_same_work(tmp_path) -> None:
    common_args = _common_verbose_args(tmp_path)
    session_result = runner.invoke(
        app,
        [
            "session",
            *common_args,
            "--session-id",
            "2026-05-12T00-00-00-test",
            "--output-format",
            "compat-json",
        ],
    )
    assert session_result.exit_code == 0, session_result.output
    assert json.loads(session_result.output)["totalTokens"] == 1100

    block_result = runner.invoke(
        app,
        [
            "blocks",
            *common_args,
            "--output-format",
            "json",
            "--recent-blocks",
            "--only-active-block",
            "--sort-order",
            "desc",
            "--block-token-limit",
            "2000",
            "--block-duration-hours",
            "5",
        ],
    )
    assert block_result.exit_code == 0, block_result.output
    assert json.loads(block_result.output)["blocks"][0]["totalTokens"] == 1100


def test_help_surfaces_verbose_caliper_flags() -> None:
    result = runner.invoke(app, ["daily", "--help"], env={"COLUMNS": "160"})

    assert result.exit_code == 0, result.output
    # Rich may abbreviate or omit option text differently across platforms.
    # The OptionInfo objects are the stable source for the public flag surface.
    # Primary names listed first; legacy aliases survive forever.
    assert {"--window-start", "--since", "-s"} <= _option_decls(cli.SinceOpt)
    assert {"--lookback-days", "--days"} <= _option_decls(cli.DaysOpt)
    assert {"--codex-session-root", "--session-root", "--from-codex"} <= _option_decls(
        cli.SessionRootOpt
    )
    assert {"--output-format", "--format", "-f"} <= _option_decls(cli.FormatOpt)
    assert {"--vendor-cost-mode", "--cost-mode", "-m", "--cost-from"} <= _option_decls(
        cli.CostModeOpt
    )


def _option_decls(annotation) -> set[str]:
    info = annotation.__metadata__[0]
    return {str(info.default), *info.param_decls}


def test_daily_compat_json_instances_and_output_file(tmp_path) -> None:
    output = tmp_path / "daily.json"
    result = runner.invoke(
        app,
        [
            "daily",
            *_common_args(tmp_path),
            "--instances",
            "--format",
            "compat-json",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text())
    assert payload["totals"]["totalTokens"] == 1100
    assert "/tmp/project-alpha" in payload["projects"]


def test_session_compat_json_shape(tmp_path) -> None:
    result = runner.invoke(app, ["session", *_common_args(tmp_path), "--format", "compat-json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["totalTokens"] == 1100
    assert payload["sessions"][0]["projectPath"] == "/tmp/project-alpha"


def test_blocks_smoke_json(tmp_path) -> None:
    result = runner.invoke(app, ["blocks", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocks"][0]["totalTokens"] == 1100
    assert payload["blocks"][0]["tokenCounts"]["inputTokens"] == 500
    assert payload["blocks"][0]["tokenCounts"]["cacheReadInputTokens"] == 500


def test_blocks_output_formats_and_filters(tmp_path) -> None:
    common_args = _common_args(tmp_path)
    for output_format in ("table", "csv", "markdown", "compat-json"):
        result = runner.invoke(
            app,
            [
                "blocks",
                *common_args,
                "--format",
                output_format,
                "--recent",
                "--active",
                "--order",
                "desc",
                "--token-limit",
                "2000",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "1100" in result.output or "1,100" in result.output


def test_blocks_honors_row_limit(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    start = dt.datetime(2026, 5, 12, 0, 0, tzinfo=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-blocks.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(
                start,
                {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            ),
            token_event(
                start + dt.timedelta(hours=6),
                {"input_tokens": 250, "output_tokens": 25, "total_tokens": 275},
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)

    result = runner.invoke(
        app,
        [
            "blocks",
            "--days",
            "1",
            "--until",
            (start + dt.timedelta(hours=7)).isoformat(),
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "--row-limit",
            "1",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["blocks"]) == 1


def test_blocks_rejects_invalid_token_limit(tmp_path) -> None:
    common_args = _common_args(tmp_path)
    result = runner.invoke(
        app,
        ["blocks", *common_args, "--token-limit", "none"],
    )
    assert result.exit_code == 2
    assert "--token-limit" in result.output

    zero = runner.invoke(app, ["blocks", *common_args, "--token-limit", "0"])
    assert zero.exit_code == 2
    assert "greater than 0" in zero.output


def test_split_instance_key_helper() -> None:
    from caliper.cli import _split_instance_key

    assert _split_instance_key("2026-05-12\0/tmp/project-alpha") == (
        "2026-05-12",
        "/tmp/project-alpha",
    )
    assert _split_instance_key("2026-05-12") == ("2026-05-12", "unknown")


def test_session_id_output_formats(tmp_path) -> None:
    session_id = "2026-05-12T00-00-00-test"
    common_args = _common_args(tmp_path)
    for output_format in ("json", "csv", "markdown", "table", "compat-json"):
        result = runner.invoke(
            app,
            [
                "session",
                *common_args,
                "--id",
                session_id,
                "--format",
                output_format,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "1100" in result.output or "1,100" in result.output


def test_project_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["project", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "project"
    assert payload["breakdowns"][0]["label"] == "<redacted-path>"


def test_models_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["models", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "models"
    assert "gpt-5.5" in payload["breakdowns"][0]["label"]


def test_grouped_reports_accept_vendor_filter(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["models", *_common_args(tmp_path), "--vendor", "openai-codex", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["events"] == 1


def test_subcommands_inherit_root_options(tmp_path) -> None:
    session_root, state_db, until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "--vendor",
            "openai-codex",
            "--format",
            "json",
            "daily",
            "--days",
            "30",
            "--until",
            until,
        ],
        env={"CODEX_HOME": str(tmp_path / "empty-codex")},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "daily"
    assert payload["totals"]["events"] == 1


def test_models_can_group_by_vendor(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["models", *_common_args(tmp_path), "--by", "vendor", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["breakdowns"][0]["key"] == "openai-codex"


def test_evidence_smoke(tmp_path) -> None:
    result = runner.invoke(app, ["evidence", *_common_args(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "evidence"
    assert payload["evidence"]["overall"] in {"exact", "estimated", "partial", "unsupported"}
    assert payload["evidence"]["dimensions"]
    assert any(row["vendor"] == "openai-codex" for row in payload["evidence"]["vendor_coverage"])


def test_rates_catalog_formats_filters_and_allow_network(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "rates-fetched.json"
    cache.write_text(
        json.dumps(
            {
                "source": "cache",
                "fetched_at": dt.datetime.now(tz=dt.UTC).isoformat(),
                "models": [
                    {
                        "name": "gpt-5.5",
                        "provider": "openai",
                        "source": "unit",
                        "api": {"input": "5", "cached_input": "0.5", "output": "30"},
                        "context_window": 400000,
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("CALIPER_DATA_DIR", str(tmp_path))

    for output_format, marker in (
        ("table", "Caliper - Pricing Catalog"),
        ("json", '"catalog"'),
        ("csv", "provider,model"),
        ("markdown", "| provider | model |"),
    ):
        args = ["rates", "catalog", "--query", "gpt", "--provider", "openai"]
        if output_format != "table":
            args.extend(["--format", output_format])
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert marker in result.output

    live_catalog = PricingCatalog(
        fetched_at=dt.datetime.now(tz=dt.UTC),
        source="unit",
        models={
            "live-model": CatalogModel(
                name="live-model",
                provider="unit",
                api_rates=Rates("1", "0.1", "2"),
                source="unit",
            )
        },
    )
    monkeypatch.setattr(
        "caliper.cli.load_cached_catalog",
        lambda: PricingCatalog(fetched_at=None, source="cache", models={}),
    )
    monkeypatch.setattr(
        "caliper.cli.load_rate_card",
        lambda _options: SimpleNamespace(pricing_catalog=live_catalog),
    )
    result = runner.invoke(app, ["rates", "catalog", "--allow-network", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert "live-model" in result.output


def test_rates_catalog_empty_cache_surfaces_warning(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CALIPER_DATA_DIR", str(tmp_path))

    result = runner.invoke(app, ["rates", "catalog", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["catalog"] == []
    assert payload["catalog_source"] == "cache"
    assert payload["embedded_available"] is True
    assert any("rates refresh --allow-network" in warning for warning in payload["warnings"])
    assert payload["using_embedded_rate_card"] is True
    assert payload["next_commands"] == ["caliper rates refresh --allow-network"]


def test_empty_overview_names_all_enabled_vendor_sources(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    result = runner.invoke(
        app,
        [
            "overview",
            "--session-root",
            str(tmp_path / "codex-empty"),
            "--state-db",
            str(tmp_path / "state.sqlite"),
            "--codex-config",
            str(tmp_path / "codex.toml"),
        ],
    )

    assert result.exit_code == 0, result.output
    for label in ("OpenAI Codex", "Claude Code", "Cursor", "Aider"):
        assert label in result.output
    assert "no files found" in result.output


def test_pr_command_requires_pr_or_range(tmp_path) -> None:
    """`caliper pr` with no number and no --range exits 2 with a helpful error."""
    session_root, state_db, _until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "pr",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
            "--git-no-network",
        ],
    )
    assert result.exit_code == 2
    assert "Provide a PR number or --range A...B." in result.output


def test_pr_resolution_guard_rejects_missing_number_and_range() -> None:
    from caliper.cli import _resolve_pr_commits

    with pytest.raises(ValueError, match="Provide a PR number or --range A...B."):
        _resolve_pr_commits(None, None, git_no_network=True)


def test_pr_command_supports_range_and_renders_zero_when_no_attribution(tmp_path) -> None:
    """`caliper pr --range A...B` against a fresh repo returns an empty per-vendor scope."""
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    session_root, state_db, _until, missing_cfg = _build(tmp_path)
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "demo@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Demo"], cwd=repo, check=True)
    (repo / "f.txt").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Demo commit"], cwd=repo, check=True)

    cwd_before = os.getcwd()
    try:
        os.chdir(repo)
        result = runner.invoke(
            app,
            [
                "pr",
                "--range",
                "HEAD~0..HEAD",
                "--session-root",
                str(session_root),
                "--state-db",
                str(state_db),
                "--codex-config",
                str(missing_cfg),
                "--format",
                "json",
                "--git-no-network",
            ],
        )
    finally:
        os.chdir(cwd_before)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["title"].startswith("Range ")
    assert "by_vendor" in payload
    # No fixture event has a git SHA matching this freshly-built repo, so by_vendor is empty.
    assert payload["by_vendor"] == []


def test_vendors_list_json(tmp_path) -> None:
    session_root, state_db, _until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "vendors",
            "list",
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
    codex = next(vendor for vendor in payload["vendors"] if vendor["id"] == "openai-codex")
    assert codex["enabled"] is True


def test_limits_smoke(tmp_path) -> None:
    """limits has its own flag surface — no --format option today."""
    session_root, state_db, until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "limits",
            "--days",
            "30",
            "--until",
            until,
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Caliper - Limits" in result.output


def test_doctor_smoke(tmp_path) -> None:
    session_root, state_db, _until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "doctor",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    # Doctor exits with status reflecting worst check (warn = 1 in fixture).
    assert result.exit_code in {0, 1}, result.output
    assert "Caliper - Doctor" in result.output
    assert "Session root" in result.output


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_invalid_since_before_until(tmp_path) -> None:
    session_root, state_db, _until, missing_cfg = _build(tmp_path)
    result = runner.invoke(
        app,
        [
            "daily",
            "--since",
            "2027-01-01",
            "--until",
            "2026-01-01",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code != 0
