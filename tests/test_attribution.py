from __future__ import annotations

import datetime as dt
from pathlib import Path

from typer.testing import CliRunner

from caliper.attribution import (
    agent_summary,
    build_agent_attributions,
    build_skill_attributions,
    skill_summary,
)
from caliper.cli import app
from caliper.config import build_options
from caliper.inefficiencies import build_inefficiency_findings
from caliper.models import LoadResult, ThreadMeta, TurnFacts, Usage, UsageEvent
from caliper.pricing import RateCard


def _card() -> RateCard:
    return RateCard.load(None, "model")


def _event(
    *,
    session: str,
    input_tokens: int = 1_000,
    output_tokens: int = 100,
    tool_names: tuple[str, ...] = (),
    skill_names: tuple[str, ...] = (),
    ts: dt.datetime | None = None,
) -> UsageEvent:
    return UsageEvent(
        timestamp=ts or dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC),
        path=Path(f"/tmp/{session}.jsonl"),
        session_id=session,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        model="claude-sonnet-4.6",
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(cwd="/tmp/project"),
        turn_facts=TurnFacts(
            tool_use_count=len(tool_names),
            tool_names=tool_names,
            skill_names=skill_names,
        ),
    )


def _result(events: list[UsageEvent]) -> LoadResult:
    return LoadResult(
        events=events,
        duplicates=0,
        tier_sources={"logged": len(events)},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )


def _options(tmp_path: Path):
    return build_options(
        days=7,
        until="2026-05-20T00:00:00Z",
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "config.toml",
    )


def test_agent_attribution_splits_known_overhead_from_direct_work() -> None:
    rows = build_agent_attributions(
        _result(
            [
                _event(session="acompact-123", input_tokens=10_000),
                _event(session="user-session", input_tokens=5_000),
            ]
        ),
        _card(),
    )

    by_category = {row.source_category: row for row in rows}
    assert by_category["overhead"].evidence_status == "exact"
    assert by_category["overhead"].agent_id == "acompact-123"
    assert by_category["direct"].evidence_status == "partial"
    summary = agent_summary(rows)
    assert summary["overhead_share"] > 0
    assert summary["direct_cost_usd_exact"] != "0"


def test_skill_attribution_uses_skill_names_and_marks_cost_estimated() -> None:
    rows = build_skill_attributions(
        _result(
            [
                _event(session="s1", tool_names=("Skill",), skill_names=("review",)),
                _event(session="s2", tool_names=("Read", "Grep")),
            ]
        ),
        _card(),
    )

    by_name = {row.name: row for row in rows}
    assert by_name["review"].evidence_status == "estimated"
    assert by_name["review"].attribution_method == "explicit-skill-turn"
    assert by_name["workflow:exploration"].attribution_method == "tool-shape"


def test_skill_summary_counts_unique_covered_events() -> None:
    result = _result(
        [
            _event(
                session="s1",
                tool_names=("Skill", "Skill"),
                skill_names=("review", "test"),
            )
        ]
    )

    rows = build_skill_attributions(result, _card())
    summary = skill_summary(rows, result)

    assert summary["covered_events"] == 1
    assert summary["coverage"] == 1.0


def test_skill_median_cost_per_invocation_is_not_mean() -> None:
    rows = build_skill_attributions(
        _result(
            [
                _event(session="s1", skill_names=("review",), input_tokens=100),
                _event(session="s2", skill_names=("review",), input_tokens=200),
                _event(session="s3", skill_names=("review",), input_tokens=10_000),
            ]
        ),
        _card(),
    )

    row = next(item for item in rows if item.name == "review")
    assert row.median_cost_per_invocation < row.cost_usd / row.invocation_count


def test_inefficiency_findings_include_overhead_tax_when_threshold_crosses(tmp_path: Path) -> None:
    result = _result(
        [
            _event(session="acompact-1", input_tokens=100_000),
            _event(session="acompact-2", input_tokens=100_000),
            _event(session="user-1", input_tokens=1_000),
        ]
    )

    findings = build_inefficiency_findings(result, _options(tmp_path), _card())

    assert any(item.code == "OVERHEAD_TAX" for item in findings)
    overhead = next(item for item in findings if item.code == "OVERHEAD_TAX")
    assert overhead.evidence_status in {"exact", "partial"}
    assert overhead.sample_size == 3


def test_agents_command_json_has_trust_labels(monkeypatch, tmp_path: Path) -> None:
    result = _result([_event(session="acompact-1", input_tokens=10_000)])
    monkeypatch.setattr("caliper.cli.load_usage", lambda options: result)
    runner = CliRunner()

    out = runner.invoke(
        app,
        [
            "agents",
            "--format",
            "json",
            "--no-parse-cache",
            "--session-root",
            str(tmp_path / "sessions"),
            "--state-db",
            str(tmp_path / "state.sqlite"),
            "--codex-config",
            str(tmp_path / "config.toml"),
        ],
    )

    assert out.exit_code == 0
    assert '"evidence_status": "exact"' in out.output
    assert "acompact-1" in out.output
