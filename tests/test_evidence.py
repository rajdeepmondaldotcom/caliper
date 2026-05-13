from __future__ import annotations

import datetime as dt
from pathlib import Path

from caliper.evidence import evidence_dimensions, evidence_metadata, evidence_rows, worst_grade
from caliper.models import (
    Aggregate,
    CostTotals,
    LoadResult,
    ParserIssue,
    RateLimitSample,
    RuntimeOptions,
    ThreadMeta,
    TierOverride,
    Usage,
    UsageEvent,
    VendorParseStats,
)


def _event(*, cwd: str = "/tmp/project", git_sha: str = "abc123") -> UsageEvent:
    return UsageEvent(
        timestamp=dt.datetime(2026, 5, 13, tzinfo=dt.UTC),
        path=Path("/tmp/session.jsonl"),
        session_id="session-1",
        usage=Usage(input_tokens=100, output_tokens=10, total_tokens=110),
        model="gpt-5.5",
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(cwd=cwd, git_sha=git_sha),
        model_source="turn_context",
        usage_source="last_token_usage",
        vendor="openai-codex",
    )


def _result(*events: UsageEvent) -> LoadResult:
    return LoadResult(
        events=list(events),
        duplicates=0,
        tier_sources={"logged": len(events)},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
    )


def test_evidence_metadata_marks_exact_loaded_events() -> None:
    result = _result(_event())
    total = Aggregate(key="total", label="Total")
    total.totals.events = 1

    payload = evidence_metadata(result, total)

    grades = {row["name"]: row["grade"] for row in payload["dimensions"]}
    assert grades["usage"] == "exact"
    assert grades["project"] == "exact"
    assert grades["git_attribution"] == "exact"


def test_evidence_dimensions_surface_partial_and_unsupported_reasons() -> None:
    result = LoadResult(
        events=[_event(cwd="", git_sha="")],
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
        parser_issues=[
            ParserIssue(
                vendor="cursor",
                kind="unsupported:no_token_usage",
                message="Cursor files have no per-event token counts",
                count=2,
                examples=("/tmp/a.jsonl",),
            )
        ],
        vendor_stats={
            "cursor": VendorParseStats(
                vendor="cursor",
                discovered_files=2,
                files_with_events=0,
                unsupported_files=2,
                event_count=0,
                warning_count=1,
            )
        },
    )
    total = Aggregate(key="total", label="Total")
    total.totals.events = 1
    total.costs = CostTotals(
        api_unpriced_events=1,
        credit_unpriced_events=1,
        estimated_events=1,
        ambiguous_reasoning_events=1,
    )
    total.unknown_model_events = 1
    total.fallback_model_events = 1
    total.unknown_tier_events = 1

    dimensions = {row.name: row for row in evidence_dimensions(result, total)}
    rows = evidence_rows(result, total)

    assert dimensions["usage"].grade == "partial"
    assert dimensions["model"].grade == "partial"
    assert dimensions["tier"].grade == "estimated"
    assert dimensions["pricing"].grade == "partial"
    assert dimensions["project"].grade == "partial"
    assert dimensions["git_attribution"].grade == "unsupported"
    assert any(row["section"] == "vendor" and row["grade"] == "unsupported" for row in rows)
    assert worst_grade(["exact", "estimated", "partial"]) == "partial"


def test_tracking_dataclass_defaults_are_stable(tmp_path) -> None:
    now = dt.datetime(2026, 5, 13, tzinfo=dt.UTC)
    options = RuntimeOptions(
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        config_path=tmp_path / "config.toml",
        start=now,
        end=now,
        timezone="UTC",
        pricing_mode="model",
        service_tier="auto",
        unknown_service_tier="current-config",
        tier_overrides=None,
        rates_file=None,
        dedupe=True,
        parse_cache=True,
        default_model="gpt-5.5",
        show_prompts=False,
        offline=True,
        compact=False,
        width=None,
        top_threads=10,
    )
    thread = ThreadMeta()
    event = UsageEvent(
        timestamp=now,
        path=tmp_path / "session.jsonl",
        session_id="session",
        usage=Usage(),
        model="gpt-5.5",
        service_tier="standard",
        tier_source="logged",
        thread=thread,
    )
    sample = RateLimitSample(timestamp=now, path=event.path, session_id=event.session_id)
    issue = ParserIssue(vendor="cursor", kind="unsupported", message="unsupported")
    stats = VendorParseStats(vendor="cursor")
    result = LoadResult(
        events=[event],
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[sample],
        warnings=[],
    )

    assert options.order == "asc"
    assert options.project is None
    assert thread.cli_version == ""
    assert TierOverride("standard").session is None
    assert event.raw_model == ""
    assert sample.vendor == "openai-codex"
    assert issue.to_record()["count"] == 1
    assert stats.to_record()["discovered_files"] == 0
    assert result.parser_issues == []
