from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from caliper.config import build_options
from caliper.efficiency import (
    ALL_CODES,
    CODE_DUPLICATE_SESSIONS,
    CODE_LONG_CONTEXT,
    CODE_LOW_CACHE_REUSE,
    CODE_MODEL_OVERSELECTION,
    CODE_PROMPT_ROT,
    CODE_REASONING_WASTE,
    CODE_TIER_MISMATCH,
    confidence_score,
    find_duplicate_sessions,
    find_long_context_misfire,
    find_low_cache_reuse,
    find_model_overselection,
    find_prompt_rot,
    find_reasoning_waste,
    find_tier_mismatch,
    monthly_projected_savings_usd,
    rank_recommendations,
    run_audit,
    total_savings_usd,
    waste_share_of_spend,
)
from caliper.models import (
    LoadResult,
    ThreadMeta,
    TurnFacts,
    Usage,
    UsageEvent,
)
from caliper.pricing import LONG_CONTEXT_INPUT_THRESHOLD, RateCard


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
    ts: dt.datetime | None = None,
    model: str = "claude-opus-4.7",
    input_tokens: int = 1_000,
    cached_input_tokens: int = 0,
    output_tokens: int = 100,
    reasoning_output_tokens: int = 0,
    total_tokens: int | None = None,
    tier: str = "standard",
    tool_use_count: int = 0,
    first_user_message: str = "do the thing",
    cwd: str = "/tmp/project",
) -> UsageEvent:
    total = (
        total_tokens
        if total_tokens is not None
        else input_tokens + output_tokens + reasoning_output_tokens
    )
    usage = Usage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
        total_tokens=total,
    )
    return UsageEvent(
        timestamp=ts or dt.datetime(2026, 5, 12, 14, 0, tzinfo=dt.UTC),
        path=Path("/tmp/rollout.jsonl"),
        session_id=session,
        usage=usage,
        model=model,
        service_tier=tier,
        tier_source="logged",
        thread=ThreadMeta(first_user_message=first_user_message, cwd=cwd),
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


# ---------------------------------------------------------------------------
# Per-finder happy-path coverage
# ---------------------------------------------------------------------------


def test_long_context_misfire_triggers_within_proximity(tmp_path: Path):
    near = int(LONG_CONTEXT_INPUT_THRESHOLD * 1.05)
    events = [_event(input_tokens=near, output_tokens=200, model="gpt-5.5") for _ in range(3)]
    findings = find_long_context_misfire(_result(events), _options(tmp_path), _card())
    assert len(findings) == 1
    assert findings[0].code == CODE_LONG_CONTEXT
    assert findings[0].impact_usd_exact > Decimal("0")


def test_long_context_misfire_does_not_trigger_when_below_threshold(tmp_path: Path):
    events = [
        _event(input_tokens=LONG_CONTEXT_INPUT_THRESHOLD - 1, model="gpt-5.5") for _ in range(3)
    ]
    assert find_long_context_misfire(_result(events), _options(tmp_path), _card()) == []


def test_long_context_misfire_skips_very_long_inputs(tmp_path: Path):
    # 2× threshold — way beyond the trim-back band.
    events = [
        _event(input_tokens=LONG_CONTEXT_INPUT_THRESHOLD * 3, model="gpt-5.5") for _ in range(3)
    ]
    assert find_long_context_misfire(_result(events), _options(tmp_path), _card()) == []


def test_reasoning_waste_triggers_on_trivial_turns(tmp_path: Path):
    events = [
        _event(output_tokens=20, reasoning_output_tokens=5_000, tool_use_count=0) for _ in range(2)
    ]
    findings = find_reasoning_waste(_result(events), _options(tmp_path), _card())
    assert len(findings) == 1
    assert findings[0].code == CODE_REASONING_WASTE
    assert findings[0].impact_usd_exact > Decimal("0")


def test_reasoning_waste_skips_when_tools_used(tmp_path: Path):
    events = [
        _event(output_tokens=100, reasoning_output_tokens=5_000, tool_use_count=3) for _ in range(2)
    ]
    assert find_reasoning_waste(_result(events), _options(tmp_path), _card()) == []


def test_low_cache_reuse_triggers_on_long_uncached_session(tmp_path: Path):
    events = [
        _event(
            session="long",
            input_tokens=100_000,
            cached_input_tokens=1_000,
            output_tokens=500,
            model="claude-sonnet-4.6",
        )
        for _ in range(3)
    ]
    findings = find_low_cache_reuse(_result(events), _options(tmp_path), _card())
    assert len(findings) == 1
    assert findings[0].code == CODE_LOW_CACHE_REUSE
    assert findings[0].impact_usd_exact > Decimal("0")
    assert findings[0].evidence[0] == "2:00 pm, Tuesday 12 May 2026"
    assert "long" not in findings[0].evidence[0]


def test_low_cache_reuse_skips_when_well_cached(tmp_path: Path):
    events = [
        _event(
            session="warm",
            input_tokens=100_000,
            cached_input_tokens=80_000,
            output_tokens=500,
            model="claude-sonnet-4.6",
        )
    ]
    assert find_low_cache_reuse(_result(events), _options(tmp_path), _card()) == []


def test_low_cache_reuse_does_not_count_cache_creation_as_reuse(tmp_path: Path):
    usage = Usage(
        input_tokens=100_000,
        cache_creation_input_tokens=80_000,
        cache_read_input_tokens=0,
        output_tokens=500,
        total_tokens=100_500,
    )
    event = UsageEvent(
        timestamp=dt.datetime(2026, 5, 12, 14, 0, tzinfo=dt.UTC),
        path=Path("/tmp/rollout.jsonl"),
        session_id="creation-only",
        usage=usage,
        model="claude-sonnet-4.6",
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(first_user_message="do the thing", cwd="/tmp/project"),
        turn_facts=TurnFacts(),
    )

    findings = find_low_cache_reuse(_result([event]), _options(tmp_path), _card())

    assert len(findings) == 1
    assert findings[0].evidence_status == "estimated"


def test_model_overselection_recommends_sibling(tmp_path: Path):
    events = [
        _event(output_tokens=100, tool_use_count=0, model="claude-opus-4.7") for _ in range(4)
    ]
    findings = find_model_overselection(_result(events), _options(tmp_path), _card())
    assert len(findings) == 1
    assert findings[0].code == CODE_MODEL_OVERSELECTION
    assert "claude-sonnet-4.6" in findings[0].evidence_metrics["sibling"]


def test_model_overselection_skips_non_trivial_turns(tmp_path: Path):
    events = [_event(output_tokens=5_000, tool_use_count=5, model="claude-opus-4.7")]
    assert find_model_overselection(_result(events), _options(tmp_path), _card()) == []


def test_tier_mismatch_triggers_on_short_priority_session(tmp_path: Path):
    events = [
        _event(session="short", tier="fast", model="gpt-5.5", output_tokens=50, input_tokens=200)
        for _ in range(2)
    ]
    findings = find_tier_mismatch(_result(events), _options(tmp_path), _card())
    assert findings
    assert findings[0].code == CODE_TIER_MISMATCH
    assert findings[0].evidence[0] == "2:00 pm, Tuesday 12 May 2026"


def test_duplicate_sessions_flag_same_prompt_within_24h(tmp_path: Path):
    base = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    events = [
        _event(session="a", ts=base, first_user_message="audit my Stripe migration"),
        _event(
            session="b",
            ts=base + dt.timedelta(hours=2),
            first_user_message="audit my Stripe migration",
        ),
        _event(
            session="c",
            ts=base + dt.timedelta(hours=4),
            first_user_message="audit my Stripe migration",
        ),
    ]
    findings = find_duplicate_sessions(_result(events), _options(tmp_path), _card())
    assert len(findings) == 1
    assert findings[0].code == CODE_DUPLICATE_SESSIONS
    assert findings[0].evidence_metrics["sessions"] == 2
    assert all(label.endswith("2026") for label in findings[0].evidence)


def test_duplicate_sessions_skips_distinct_prompts(tmp_path: Path):
    base = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    events = [
        _event(session="a", ts=base, first_user_message="prompt one"),
        _event(session="b", ts=base + dt.timedelta(hours=2), first_user_message="prompt two"),
    ]
    assert find_duplicate_sessions(_result(events), _options(tmp_path), _card()) == []


def test_prompt_rot_flags_doubling_uncached_input(tmp_path: Path):
    base = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    events = []
    for i in range(6):
        events.append(
            _event(
                session="rotting",
                ts=base + dt.timedelta(minutes=10 * i),
                input_tokens=1_000 * (i + 1) * 2,
                output_tokens=80,
                model="claude-sonnet-4.6",
            )
        )
    findings = find_prompt_rot(_result(events), _options(tmp_path), _card())
    assert len(findings) == 1
    assert findings[0].code == CODE_PROMPT_ROT
    assert findings[0].evidence[0] == "12:00 pm, Tuesday 12 May 2026"


def test_prompt_rot_skips_when_output_also_grows(tmp_path: Path):
    base = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
    events = []
    for i in range(6):
        events.append(
            _event(
                session="balanced",
                ts=base + dt.timedelta(minutes=10 * i),
                input_tokens=1_000 * (i + 1) * 2,
                output_tokens=500 * (i + 1) * 2,
                model="claude-sonnet-4.6",
            )
        )
    assert find_prompt_rot(_result(events), _options(tmp_path), _card()) == []


# ---------------------------------------------------------------------------
# Registry, audit, ranker
# ---------------------------------------------------------------------------


def test_all_codes_have_finders(tmp_path: Path):
    from caliper.efficiency import FINDER_REGISTRY

    assert set(ALL_CODES) == set(FINDER_REGISTRY)


def test_run_audit_filters_by_min_impact(tmp_path: Path):
    near = int(LONG_CONTEXT_INPUT_THRESHOLD * 1.05)
    events = [_event(input_tokens=near, output_tokens=200, model="gpt-5.5")]
    findings = run_audit(
        _result(events),
        _options(tmp_path),
        _card(),
        min_impact_usd=Decimal("9999"),
    )
    assert findings == []


def test_run_audit_returns_sorted_by_impact(tmp_path: Path):
    events = [
        _event(
            input_tokens=int(LONG_CONTEXT_INPUT_THRESHOLD * 1.05),
            output_tokens=200,
            model="gpt-5.5",
        ),
        _event(output_tokens=50, reasoning_output_tokens=10_000),
    ]
    findings = run_audit(_result(events), _options(tmp_path), _card())
    impacts = [float(f.impact_usd_exact) for f in findings]
    assert impacts == sorted(impacts, reverse=True)


def test_run_audit_preserves_evidence_metadata_after_dedupe(tmp_path: Path):
    near = int(LONG_CONTEXT_INPUT_THRESHOLD * 1.05)
    events = [_event(input_tokens=near, output_tokens=200, model="gpt-5.5")]

    findings = run_audit(_result(events), _options(tmp_path), _card())

    assert findings
    assert findings[0].evidence_status
    assert findings[0].sample_size == 1
    assert findings[0].baseline


def test_run_audit_skips_unknown_codes(tmp_path: Path):
    near = int(LONG_CONTEXT_INPUT_THRESHOLD * 1.05)
    events = [_event(input_tokens=near, output_tokens=200, model="gpt-5.5") for _ in range(3)]
    findings = run_audit(
        _result(events),
        _options(tmp_path),
        _card(),
        codes=["DOES_NOT_EXIST", CODE_LONG_CONTEXT],
    )
    assert len(findings) == 1


def test_total_and_monthly_helpers(tmp_path: Path):
    near = int(LONG_CONTEXT_INPUT_THRESHOLD * 1.05)
    events = [_event(input_tokens=near, output_tokens=200, model="gpt-5.5") for _ in range(3)]
    findings = run_audit(_result(events), _options(tmp_path), _card())
    total = total_savings_usd(findings)
    monthly = monthly_projected_savings_usd(findings)
    assert total > Decimal("0")
    assert monthly >= total  # window is 14d, scale = 30/14 > 1


def test_rank_recommendations_top_n(tmp_path: Path):
    events = [
        _event(
            input_tokens=int(LONG_CONTEXT_INPUT_THRESHOLD * 1.05),
            output_tokens=200,
            model="gpt-5.5",
        ),
        _event(output_tokens=50, reasoning_output_tokens=10_000),
        _event(output_tokens=100, model="claude-opus-4.7"),
    ]
    findings = run_audit(_result(events), _options(tmp_path), _card())
    recs = rank_recommendations(findings, top=2)
    assert len(recs) <= 2
    for index, rec in enumerate(recs):
        assert rec.rank == index + 1


def test_waste_share_of_spend_handles_zero_spend():
    assert waste_share_of_spend([], Decimal("0")) == 0.0


def test_confidence_score_empty_returns_zero():
    assert confidence_score([]) == 0.0


@pytest.mark.parametrize("code", ALL_CODES)
def test_finder_runs_on_empty_result(tmp_path: Path, code: str):
    from caliper.efficiency import FINDER_REGISTRY

    findings = FINDER_REGISTRY[code](
        _result([]),
        _options(tmp_path),
        _card(),
    )
    assert findings == []
