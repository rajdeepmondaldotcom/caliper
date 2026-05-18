from __future__ import annotations

import datetime as dt
from pathlib import Path

from caliper.dedupe import dedupe_rate_limit_samples, dedupe_usage_events
from caliper.models import RateLimitSample, ThreadMeta, Usage, UsageEvent


def _event(
    *,
    path: Path = Path("/tmp/session-a.jsonl"),
    session_id: str = "session-a",
    timestamp: dt.datetime = dt.datetime(2026, 5, 12, 10, tzinfo=dt.UTC),
    event_id: str = "",
    message_id: str = "",
    request_id: str = "",
    dedupe_key: str = "",
    input_tokens: int = 100,
    output_tokens: int = 10,
    cwd: str = "/tmp/project",
) -> UsageEvent:
    return UsageEvent(
        timestamp=timestamp,
        path=path,
        session_id=session_id,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        model="gpt-5.5",
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(cwd=cwd),
        vendor="openai-codex",
        event_id=event_id,
        message_id=message_id,
        request_id=request_id,
        dedupe_key=dedupe_key,
    )


def test_usage_dedupe_matches_secondary_identity_when_primary_identity_differs() -> None:
    first = _event(event_id="event-a", message_id="message-1", request_id="request-1")
    second = _event(event_id="event-b", message_id="message-1", request_id="request-1")

    events, stats = dedupe_usage_events([first, second])

    assert events == [first]
    assert stats.duplicates == 1
    assert stats.by_strategy == {"message_request": 1}


def test_usage_dedupe_preserves_distinct_event_ids_even_when_usage_matches() -> None:
    first = _event(event_id="event-a")
    second = _event(event_id="event-b")

    events, stats = dedupe_usage_events([first, second])

    assert events == [first, second]
    assert stats.duplicates == 0


def test_usage_dedupe_preserves_same_event_id_from_different_sessions() -> None:
    first = _event(event_id="event-a", session_id="session-a")
    second = _event(event_id="event-a", session_id="session-b")

    events, stats = dedupe_usage_events([first, second])

    assert events == [first, second]
    assert stats.duplicates == 0


def test_usage_dedupe_preserves_same_request_id_when_messages_differ() -> None:
    first = _event(message_id="message-a", request_id="request-1")
    second = _event(message_id="message-b", request_id="request-1")

    events, stats = dedupe_usage_events([first, second])

    assert events == [first, second]
    assert stats.duplicates == 0


def test_usage_dedupe_preserves_reused_request_id_when_usage_differs() -> None:
    first = _event(request_id="request-1", input_tokens=100)
    second = _event(request_id="request-1", input_tokens=101)

    events, stats = dedupe_usage_events([first, second])

    assert events == [first, second]
    assert stats.duplicates == 0


def test_usage_dedupe_matches_request_id_only_when_usage_matches() -> None:
    first = _event(request_id="request-1")
    second = _event(request_id="request-1")

    events, stats = dedupe_usage_events([first, second])

    assert events == [first]
    assert stats.duplicates == 1
    assert stats.by_strategy == {"request_id": 1}


def test_usage_dedupe_is_always_on_even_if_disabled_flag_is_passed() -> None:
    first = _event(dedupe_key="same-event")
    second = _event(dedupe_key="same-event")

    events, stats = dedupe_usage_events([first, second], enabled=False)

    assert events == [first]
    assert stats.duplicates == 1
    assert stats.by_strategy == {"dedupe_key": 1}


def test_semantic_usage_dedupe_ignores_copied_file_path() -> None:
    first = _event(path=Path("/tmp/original/rollout-session.jsonl"))
    second = _event(path=Path("/tmp/copy/rollout-session.jsonl"))

    events, stats = dedupe_usage_events([first, second])

    assert events == [first]
    assert stats.by_strategy == {"semantic_usage": 1}


def test_semantic_usage_dedupe_preserves_identical_usage_from_different_sessions() -> None:
    first = _event(session_id="session-a")
    second = _event(session_id="session-b")

    events, stats = dedupe_usage_events([first, second])

    assert events == [first, second]
    assert stats.duplicates == 0


def test_rate_limit_sample_dedupe_ignores_copied_file_path() -> None:
    timestamp = dt.datetime(2026, 5, 12, 10, tzinfo=dt.UTC)
    first = RateLimitSample(
        timestamp=timestamp,
        path=Path("/tmp/original/rollout-session.jsonl"),
        session_id="session-a",
        plan_type="pro",
        limit_id="codex",
        primary_used_percent=25.0,
        primary_window_minutes=300,
        primary_resets_at=1,
        secondary_used_percent=75.0,
        secondary_window_minutes=10080,
        secondary_resets_at=2,
    )
    second = RateLimitSample(
        timestamp=timestamp,
        path=Path("/tmp/copy/rollout-session.jsonl"),
        session_id="session-a",
        plan_type="pro",
        limit_id="codex",
        primary_used_percent=25.0,
        primary_window_minutes=300,
        primary_resets_at=1,
        secondary_used_percent=75.0,
        secondary_window_minutes=10080,
        secondary_resets_at=2,
    )

    samples, stats = dedupe_rate_limit_samples([first, second])

    assert samples == [first]
    assert stats.duplicates == 1
    assert stats.by_strategy == {"rate_limit_sample": 1}
