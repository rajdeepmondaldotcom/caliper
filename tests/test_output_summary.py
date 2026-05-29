"""The "what did this produce?" output summary.

These guard the honesty contract of the leverage view: every figure is
derived from local evidence (git SHAs on events plus tool-call counts),
``cost_per_commit`` reconciles with ``linked_cost / commits_touched``, the
no-git path still reports the tool mix, and an empty window yields nothing
to render.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from caliper.analysis.session_shape import compute_session_shape
from caliper.dashboards.adapter import _build_output_summary
from caliper.dashboards.html import render_dashboard
from caliper.dashboards.sample_data import sample_dashboard
from caliper.models import (
    VENDOR_CLAUDE_CODE,
    LoadResult,
    ThreadMeta,
    TurnFacts,
    Usage,
    UsageEvent,
)
from caliper.pricing import RateCard


def _card() -> RateCard:
    return RateCard.load(None, "model")


def _event(
    *,
    session_id: str,
    turn_index: int,
    tools: tuple[str, ...],
    git_sha: str = "",
    minute: int = 0,
) -> UsageEvent:
    return UsageEvent(
        timestamp=dt.datetime(2026, 5, 12, 10, minute, tzinfo=dt.UTC),
        path=Path("/dev/null"),
        session_id=session_id,
        usage=Usage(input_tokens=1000, output_tokens=200),
        model="claude-sonnet-4-6",
        service_tier="standard",
        tier_source="vendor-default",
        thread=ThreadMeta(cwd="/tmp/project-alpha", source=VENDOR_CLAUDE_CODE, git_sha=git_sha),
        vendor=VENDOR_CLAUDE_CODE,
        turn_facts=TurnFacts(
            turn_index=turn_index,
            tool_use_count=len(tools),
            tool_names=tuple(tools),
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


def test_output_summary_links_spend_to_commits() -> None:
    card = _card()
    events = [
        _event(session_id="s1", turn_index=0, tools=("Edit",), git_sha="aaa", minute=1),
        _event(session_id="s1", turn_index=1, tools=("Bash",), git_sha="aaa", minute=2),
        _event(session_id="s2", turn_index=0, tools=("Edit",), git_sha="bbb", minute=3),
    ]
    result = _result(events)
    summary = _build_output_summary(result, card, compute_session_shape(result))

    assert summary is not None
    assert summary.has_git is True
    # Two distinct SHAs were checked out while AI worked.
    assert summary.commits_touched == 2
    # Cost per commit reconciles with git-linked spend by construction.
    assert summary.linked_cost_usd > 0
    assert summary.cost_per_commit_usd == summary.linked_cost_usd / 2
    # All three events carried a SHA, so linkage is total.
    assert summary.linked_cost_pct == 1.0
    # Two edits and one diagnostic across three classified calls.
    assert round(summary.edit_share, 3) == round(2 / 3, 3)
    assert round(summary.diagnostic_share, 3) == round(1 / 3, 3)


def test_output_summary_without_git_still_reports_tool_mix() -> None:
    card = _card()
    events = [
        _event(session_id="s1", turn_index=0, tools=("Bash",), minute=1),
        _event(session_id="s1", turn_index=1, tools=("Read",), minute=2),
    ]
    result = _result(events)
    summary = _build_output_summary(result, card, compute_session_shape(result))

    assert summary is not None
    assert summary.has_git is False
    assert summary.commits_touched == 0
    assert summary.cost_per_commit_usd == 0.0
    assert summary.classified_tool_calls == 2
    assert "No git history" in summary.caveat


def test_output_summary_uses_authored_commits_when_provided() -> None:
    card = _card()
    events = [
        # One linked event (carries a SHA) and one unlinked, so total > linked.
        _event(session_id="s1", turn_index=0, tools=("Edit",), git_sha="aaa", minute=1),
        _event(session_id="s2", turn_index=0, tools=("Edit",), minute=2),
    ]
    result = _result(events)
    summary = _build_output_summary(result, card, compute_session_shape(result), authored_commits=5)

    assert summary is not None
    assert summary.has_git is True
    assert summary.commits_from_git is True
    # The git-authored count wins over the 1-distinct-SHA proxy.
    assert summary.commits_touched == 5
    # Cost per commit is TOTAL window spend over authored commits, not just
    # the git-linked slice, so it exceeds linked_cost / 5.
    assert summary.cost_per_commit_usd * 5 > summary.linked_cost_usd
    assert summary.linked_cost_pct < 1.0
    assert "Commits authored" in summary.caveat


def test_output_summary_zero_authored_commits_falls_back_to_proxy() -> None:
    # authored_commits=0 means local git surfaced nothing; keep the proxy.
    card = _card()
    events = [_event(session_id="s1", turn_index=0, tools=("Edit",), git_sha="aaa")]
    result = _result(events)
    summary = _build_output_summary(result, card, compute_session_shape(result), authored_commits=0)

    assert summary is not None
    assert summary.commits_from_git is False
    assert summary.commits_touched == 1


def test_output_summary_caveats_unclassified_tools() -> None:
    # A tool that isn't in the edit/diagnose/explore sets must be disclosed,
    # not silently dropped from the denominator behind a clean-looking 100%.
    card = _card()
    events = [
        _event(session_id="s1", turn_index=0, tools=("Edit",), minute=1),
        _event(session_id="s1", turn_index=1, tools=("TotallyNewTool",), minute=2),
    ]
    result = _result(events)
    summary = _build_output_summary(result, card, compute_session_shape(result))

    assert summary is not None
    # Only the Edit call is classified; the unknown tool is the other half.
    assert summary.classified_tool_calls == 1
    assert "unrecognized kind" in summary.caveat
    assert "50%" in summary.caveat


def test_output_summary_none_on_empty_window() -> None:
    assert _build_output_summary(_result([]), _card(), compute_session_shape(_result([]))) is None


def test_output_section_renders_in_dashboard() -> None:
    html = render_dashboard(sample_dashboard())
    assert 'id="output"' in html
    assert "What this produced" in html
    assert "Commits touched" in html
    assert "Cost per commit" in html
