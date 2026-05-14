from __future__ import annotations

import datetime as dt
import json

from typer.testing import CliRunner

from caliper.aggregation import aggregate_daily, aggregate_projects, aggregate_total
from caliper.cli import app
from caliper.config import build_options
from caliper.insights import (
    Insight,
    build_insights,
    build_insights_from,
    render_insights_markdown,
)
from caliper.models import LoadResult
from caliper.pricing import load_rate_card

from .conftest import make_state_db, token_event, write_session

runner = CliRunner()


def _fixture(tmp_path) -> tuple:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-insights.jsonl",
        [
            {
                "type": "turn_context",
                "timestamp": "2026-05-12T00:00:00Z",
                "payload": {"model": "gpt-5.5"},
            },
            token_event(
                now,
                {
                    "input_tokens": 10_000,
                    "cached_input_tokens": 9_000,
                    "output_tokens": 1_000,
                    "reasoning_output_tokens": 250,
                    "total_tokens": 11_000,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    return session_root, state_db, tmp_path / "missing.toml"


def test_insights_json_reports_cache_tier_and_project_concentration(tmp_path) -> None:
    session_root, state_db, missing_cfg = _fixture(tmp_path)
    result = runner.invoke(
        app,
        [
            "insights",
            "--days",
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
    titles = {item["title"] for item in payload["insights"]}
    assert "High cache reuse" in titles
    assert "Service tier inferred" in titles
    assert any("is 100% of cost" in title for title in titles)  # project concentration
    cache = next(item for item in payload["insights"] if item["title"] == "High cache reuse")
    assert cache["category"] == "cache"
    assert cache["priority"] > 0
    assert cache["confidence"] == "high"
    assert cache["impact_usd_exact"]
    assert cache["evidence_metrics"]["cache_hit_ratio"] > 0
    assert isinstance(cache["commands"], list)


def test_insights_markdown_renders_actions(tmp_path) -> None:
    session_root, state_db, missing_cfg = _fixture(tmp_path)
    result = runner.invoke(
        app,
        [
            "insights",
            "--days",
            "1",
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
    assert "| Severity | Insight | Detail | Action |" in result.output
    assert "caliper project" in result.output


def test_build_insights_returns_empty_for_empty_usage(tmp_path) -> None:
    options = build_options(
        session_root=tmp_path / "missing-sessions",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
    )
    result = LoadResult(
        events=[],
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )

    assert build_insights(result, options) == []


def test_build_insights_from_matches_wrapper(tmp_path) -> None:
    from caliper.parser import load_usage

    session_root, state_db, missing_cfg = _fixture(tmp_path)
    options = build_options(
        session_root=session_root,
        state_db=state_db,
        codex_config=missing_cfg,
        days=1,
    )
    result = load_usage(options)
    card = load_rate_card(options)
    total = aggregate_total(result, options, rate_card=card)
    projects = aggregate_projects(result, options, rate_card=card)
    daily = aggregate_daily(result, options, rate_card=card)

    wrapper = build_insights(result, options, rate_card=card)
    direct = build_insights_from(
        result=result,
        rate_card=card,
        total=total,
        projects=projects,
        daily=daily,
    )
    assert wrapper == direct


def test_insights_markdown_escapes_pipe_characters() -> None:
    output = render_insights_markdown(
        [
            Insight(
                severity="info",
                title="A | B",
                detail="one | two",
                action="run | inspect",
            )
        ]
    )

    assert "A \\| B" in output
    assert "one \\| two" in output
