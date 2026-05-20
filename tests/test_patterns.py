from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from caliper.models import ThreadMeta, TurnFacts, Usage, UsageEvent
from caliper.patterns import (
    SHAPE_LARGE,
    SHAPE_MEDIUM,
    SHAPE_SMALL,
    classify_all_sessions,
    classify_session_shape,
    daily_buckets,
    hour_dow_buckets,
    is_trivial_turn,
    per_model_daily_tokens,
    project_for_event,
    prompt_rot_curve,
    session_event_groups,
    session_first_prompt_hash,
    session_token_totals,
    shape_cutoffs,
)


def _event(
    *,
    session: str = "s1",
    ts: dt.datetime = dt.datetime(2026, 5, 12, 14, 0, tzinfo=dt.UTC),
    input_tokens: int = 100,
    cached_input_tokens: int = 0,
    output_tokens: int = 100,
    total_tokens: int | None = None,
    model: str = "gpt-5.5",
    first_user_message: str = "do the thing",
    cwd: str = "/tmp/project",
    tool_use_count: int = 0,
) -> UsageEvent:
    total = total_tokens if total_tokens is not None else input_tokens + output_tokens
    usage = Usage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
    )
    return UsageEvent(
        timestamp=ts,
        path=Path("/tmp/rollout.jsonl"),
        session_id=session,
        usage=usage,
        model=model,
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(first_user_message=first_user_message, cwd=cwd),
        turn_facts=TurnFacts(tool_use_count=tool_use_count),
    )


def test_session_token_totals_sums_per_session():
    events = [
        _event(session="a", total_tokens=100),
        _event(session="a", total_tokens=50),
        _event(session="b", total_tokens=200),
    ]
    assert session_token_totals(events) == {"a": 150, "b": 200}


def test_session_token_totals_skips_empty_sessions():
    events = [_event(session="", total_tokens=100), _event(session="a", total_tokens=20)]
    assert session_token_totals(events) == {"a": 20}


def test_shape_cutoffs_empty_returns_zero():
    assert shape_cutoffs([]) == (0, 0)


def test_shape_cutoffs_single_value():
    assert shape_cutoffs([42]) == (42, 42)


def test_shape_cutoffs_six_values_returns_tertile_breaks():
    low, high = shape_cutoffs([10, 20, 30, 40, 50, 60])
    assert low <= 20
    assert high >= 40


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (10, SHAPE_SMALL),
        (50, SHAPE_MEDIUM),
        (200, SHAPE_LARGE),
    ],
)
def test_classify_session_shape_buckets(tokens, expected):
    assert classify_session_shape(tokens, (20, 100)) == expected


def test_classify_all_sessions_grouped():
    events = [
        _event(session="tiny", total_tokens=5),
        _event(session="mid", total_tokens=50),
        _event(session="huge", total_tokens=5_000),
    ]
    result = classify_all_sessions(events)
    assert result["tiny"] == SHAPE_SMALL
    assert result["huge"] == SHAPE_LARGE


def test_hour_dow_buckets_assigns_local_tz_correctly():
    # 2026-05-12 14:00 UTC = 19:30 IST (UTC+5:30)
    e = _event(ts=dt.datetime(2026, 5, 12, 14, 0, tzinfo=dt.UTC))
    hours, dows = hour_dow_buckets([e], "Asia/Kolkata", cost_fn=lambda _e: 1.0)
    assert hours[19] == pytest.approx(1.0)
    # 2026-05-12 was a Tuesday.
    assert dows[1] == pytest.approx(1.0)


def test_session_first_prompt_hash_stable_and_truncated():
    event = _event(first_user_message="Refactor the parser to handle X")
    digest = session_first_prompt_hash(event)
    assert len(digest) == 16
    assert digest == session_first_prompt_hash(event)


def test_session_first_prompt_hash_empty_returns_empty():
    event = _event(first_user_message="")
    assert session_first_prompt_hash(event) == ""


def test_prompt_rot_curve_chronological():
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    events = [
        _event(ts=base + dt.timedelta(minutes=10), input_tokens=200, total_tokens=300),
        _event(ts=base, input_tokens=100, total_tokens=200),
        _event(ts=base + dt.timedelta(minutes=20), input_tokens=400, total_tokens=500),
    ]
    curve = prompt_rot_curve(events)
    assert curve == [100, 200, 400]


def test_prompt_rot_curve_empty_returns_empty():
    assert prompt_rot_curve([]) == []


def test_is_trivial_turn_true_for_short_no_tool_event():
    assert is_trivial_turn(_event(output_tokens=100, input_tokens=200, tool_use_count=0))


def test_is_trivial_turn_false_when_tools_used():
    assert not is_trivial_turn(_event(tool_use_count=3))


def test_is_trivial_turn_false_when_output_large():
    assert not is_trivial_turn(_event(output_tokens=10_000))


def test_session_event_groups_skips_empty_session_id():
    events = [_event(session="x"), _event(session="x"), _event(session="")]
    groups = session_event_groups(events)
    assert len(groups["x"]) == 2
    assert "" not in groups


def test_project_for_event_falls_back():
    assert project_for_event(_event(cwd="")) == "unknown"
    assert project_for_event(_event(cwd="/srv/app")) == "/srv/app"


def test_daily_buckets_local_tz():
    e = _event(ts=dt.datetime(2026, 5, 12, 22, 0, tzinfo=dt.UTC))
    buckets = daily_buckets([e], "Asia/Kolkata", value_fn=lambda _e: 1.0)
    # 22:00 UTC = 03:30 next day IST
    assert buckets == {dt.date(2026, 5, 13): 1.0}


def test_per_model_daily_tokens_groups_correctly():
    base = dt.datetime(2026, 5, 12, 10, 0, tzinfo=dt.UTC)
    events = [
        _event(ts=base, model="gpt-5.5", total_tokens=100),
        _event(ts=base + dt.timedelta(days=1), model="gpt-5.5", total_tokens=50),
        _event(ts=base, model="claude-opus-4.7", total_tokens=200),
    ]
    result = per_model_daily_tokens(events, "UTC")
    assert result["gpt-5.5"][dt.date(2026, 5, 12)] == 100
    assert result["gpt-5.5"][dt.date(2026, 5, 13)] == 50
    assert result["claude-opus-4.7"][dt.date(2026, 5, 12)] == 200
