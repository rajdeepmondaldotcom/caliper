"""The single-source-of-truth recommendation selector.

These guard the budget-meeting contract: the headline "fixable $X" sums
exactly the shown rows, ``--strict`` is a subset of the default view, and
the canonical default window is shared, so a number from one surface
reconciles with every other.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from caliper.config import DEFAULT_WINDOW_DAYS, build_options, load_dashboard_config
from caliper.models import (
    LoadResult,
    ThreadMeta,
    TurnFacts,
    Usage,
    UsageEvent,
)
from caliper.pricing import RateCard
from caliper.recommendations import RecommendationSet, select_recommendations


def _card() -> RateCard:
    return RateCard.load(None, "model")


def _options(tmp_path: Path):
    return build_options(
        days=14,
        until="2026-05-20T00:00:00Z",
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "config.toml",
        timezone="UTC",
    )


def _event(
    *,
    session: str = "s1",
    model: str = "gpt-5.5",
    input_tokens: int = 1_000,
    output_tokens: int = 20,
    reasoning_output_tokens: int = 0,
    tier: str = "priority",
    tool_use_count: int = 0,
) -> UsageEvent:
    usage = Usage(
        input_tokens=input_tokens,
        cached_input_tokens=0,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
        total_tokens=input_tokens + output_tokens + reasoning_output_tokens,
    )
    return UsageEvent(
        timestamp=dt.datetime(2026, 5, 12, 14, 0, tzinfo=dt.UTC),
        path=Path("/tmp/rollout.jsonl"),
        session_id=session,
        usage=usage,
        model=model,
        service_tier=tier,
        tier_source="logged",
        thread=ThreadMeta(first_user_message="do the thing", cwd="/tmp/project"),
        turn_facts=TurnFacts(tool_use_count=tool_use_count),
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


def _busy_result() -> LoadResult:
    # A mix that trips several finders so there is more than one finding.
    events: list[UsageEvent] = []
    for i in range(40):
        events.append(
            _event(session=f"opus{i}", model="claude-opus-4.7", reasoning_output_tokens=5_000)
        )
    for i in range(40):
        events.append(_event(session=f"cheap{i}", model="gpt-5.5", output_tokens=10))
    return _result(events)


def test_fixable_shown_sums_exactly_the_ranked_rows(tmp_path: Path):
    selection = select_recommendations(_busy_result(), _options(tmp_path), _card(), top=3)
    assert isinstance(selection, RecommendationSet)
    expected = sum((r.impact_usd_exact for r in selection.ranked), Decimal("0"))
    # "Fixable $X across N" must reconcile by construction.
    assert selection.fixable_shown_usd == expected
    assert selection.shown_count == len(selection.ranked) <= 3


def test_fixable_shown_never_exceeds_full_audit_total(tmp_path: Path):
    selection = select_recommendations(_busy_result(), _options(tmp_path), _card(), top=2)
    assert selection.fixable_shown_usd <= selection.total_savings_usd
    assert selection.total_findings >= selection.shown_count


def test_strict_is_a_subset_of_the_default_view(tmp_path: Path):
    result, options, card = _busy_result(), _options(tmp_path), _card()
    default = select_recommendations(result, options, card, top=10)
    strict = select_recommendations(result, options, card, top=10, strict=True)
    default_codes = {r.source_code for r in default.ranked}
    strict_codes = {r.source_code for r in strict.ranked}
    assert strict_codes <= default_codes
    # Strict keeps only high-confidence findings.
    assert all(f.confidence == "high" for f in strict.findings)


def test_top_fix_is_the_first_ranked_recommendation(tmp_path: Path):
    selection = select_recommendations(_busy_result(), _options(tmp_path), _card(), top=5)
    if selection.ranked:
        assert selection.top_fix is selection.ranked[0]
    else:
        assert selection.top_fix is None


def test_default_window_is_unified_across_cli_and_dashboard():
    # With no config pinning a window, the CLI fallback and the dashboard
    # default must agree on DEFAULT_WINDOW_DAYS so surfaces match out of box.
    assert load_dashboard_config({}).default_days == DEFAULT_WINDOW_DAYS
    # And the dashboard inherits a top-level default_days when it doesn't
    # pin its own — one knob governs both.
    assert load_dashboard_config({"default_days": 21}).default_days == 21
    assert (
        load_dashboard_config({"default_days": 21, "dashboard": {"default_days": 9}}).default_days
        == 9
    )
