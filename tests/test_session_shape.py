from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

from caliper.analysis.session_shape import (
    CATEGORY_DIAGNOSTIC,
    CATEGORY_EXECUTION,
    CATEGORY_EXPLORATION,
    CATEGORY_MIXED,
    CATEGORY_NONE,
    classify_session,
    compute_session_shape,
)
from caliper.models import (
    VENDOR_CLAUDE_CODE,
    LoadResult,
    ThreadMeta,
    TurnFacts,
    Usage,
    UsageEvent,
)


def _event(
    *,
    session_id: str,
    turn_index: int,
    tools: tuple[str, ...],
    minute: int = 0,
    cwd: str = "/tmp/project-alpha",
) -> UsageEvent:
    return UsageEvent(
        timestamp=dt.datetime(2026, 5, 12, 10, minute, tzinfo=dt.UTC),
        path=Path("/dev/null"),
        session_id=session_id,
        usage=Usage(input_tokens=100, output_tokens=10),
        model="claude-sonnet-4-6",
        service_tier="standard",
        tier_source="vendor-default",
        thread=ThreadMeta(cwd=cwd, source=VENDOR_CLAUDE_CODE),
        vendor=VENDOR_CLAUDE_CODE,
        turn_facts=TurnFacts(
            turn_index=turn_index,
            tool_use_count=len(tools),
            tool_names=tuple(sorted(set(tools))),
        ),
    )


def _result(events: list[UsageEvent]) -> LoadResult:
    return LoadResult(
        events=events,
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )


def test_classify_session_categories() -> None:
    assert classify_session(Counter({"Read": 8, "Grep": 2})) == CATEGORY_EXPLORATION
    assert classify_session(Counter({"Edit": 6, "Write": 4})) == CATEGORY_EXECUTION
    assert classify_session(Counter({"Bash": 10})) == CATEGORY_DIAGNOSTIC
    assert classify_session(Counter({"Read": 2, "Edit": 2, "Bash": 2})) == CATEGORY_MIXED
    assert classify_session(Counter()) == CATEGORY_NONE


def test_session_shape_aggregates_tool_calls() -> None:
    events = [
        _event(session_id="s1", turn_index=0, tools=("Read", "Edit"), minute=1),
        _event(session_id="s1", turn_index=1, tools=("Read",), minute=2),
        _event(session_id="s2", turn_index=0, tools=("Bash",), minute=3),
    ]
    report = compute_session_shape(_result(events))

    assert report.total_sessions == 2
    assert report.total_turns == 3
    assert report.tool_use.total_calls == 4
    tools_dict = dict(report.tool_use.per_tool)
    assert tools_dict["Read"] == 2
    assert tools_dict["Edit"] == 1
    assert tools_dict["Bash"] == 1
    assert {item.session_id for item in report.sessions} == {"s1", "s2"}


def test_session_shape_categorizes_sessions() -> None:
    events = [
        _event(session_id="explore", turn_index=0, tools=("Read", "Grep")),
        _event(session_id="explore", turn_index=1, tools=("Read",), minute=1),
        _event(session_id="edit", turn_index=0, tools=("Edit",), minute=2),
        _event(session_id="edit", turn_index=1, tools=("Write",), minute=3),
    ]
    report = compute_session_shape(_result(events))
    cats = {item.session_id: item.category for item in report.sessions}
    assert cats["explore"] == CATEGORY_EXPLORATION
    assert cats["edit"] == CATEGORY_EXECUTION


def test_session_shape_handles_no_turn_facts() -> None:
    events = [
        UsageEvent(
            timestamp=dt.datetime(2026, 5, 12, 10, tzinfo=dt.UTC),
            path=Path("/dev/null"),
            session_id="bare",
            usage=Usage(input_tokens=100, output_tokens=10),
            model="x",
            service_tier="standard",
            tier_source="vendor-default",
            thread=ThreadMeta(),
        )
    ]
    report = compute_session_shape(_result(events))
    assert report.total_sessions == 0
    assert report.coverage_total_events == 1
    assert report.coverage_events == 0


def test_session_shape_daily_groups_by_day() -> None:
    events = [
        _event(session_id="s1", turn_index=0, tools=("Read",), minute=1),
        _event(session_id="s1", turn_index=1, tools=("Edit",), minute=5),
    ]
    report = compute_session_shape(_result(events))
    assert len(report.daily) == 1
    assert report.daily[0].turns == 2
    assert report.daily[0].tool_uses == 2
