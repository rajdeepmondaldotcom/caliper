"""Pure feature extraction over UsageEvents.

Used by :mod:`caliper.predict`, :mod:`caliper.anomaly`, and
:mod:`caliper.efficiency`. No I/O, no network, stdlib only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections import defaultdict
from collections.abc import Iterable

from caliper.models import UsageEvent
from caliper.timeutil import load_timezone

SHAPE_SMALL = "small"
SHAPE_MEDIUM = "medium"
SHAPE_LARGE = "large"
SHAPE_LABELS: tuple[str, ...] = (SHAPE_SMALL, SHAPE_MEDIUM, SHAPE_LARGE)

TRIVIAL_OUTPUT_TOKENS = 500
TRIVIAL_INPUT_TOKENS = 2_000


def session_token_totals(events: Iterable[UsageEvent]) -> dict[str, int]:
    """Sum total_tokens per session_id."""
    totals: dict[str, int] = defaultdict(int)
    for event in events:
        if not event.session_id:
            continue
        totals[event.session_id] += event.usage.total_tokens
    return dict(totals)


def shape_cutoffs(values: list[int]) -> tuple[int, int]:
    """Return (low, high) tertile cutoffs over sorted values.

    Returns ``(0, 0)`` for empty input; ``(v, v)`` for single-value
    input. Edge cases are handled so callers can always classify.
    """
    if not values:
        return 0, 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0], ordered[0]
    low_index = max(0, len(ordered) // 3 - 1)
    high_index = min(len(ordered) - 1, (2 * len(ordered)) // 3)
    return ordered[low_index], ordered[high_index]


def classify_session_shape(total_tokens: int, cutoffs: tuple[int, int]) -> str:
    """Return ``small`` / ``medium`` / ``large`` for a token total."""
    low, high = cutoffs
    if total_tokens <= low:
        return SHAPE_SMALL
    if total_tokens >= high:
        return SHAPE_LARGE
    return SHAPE_MEDIUM


def classify_all_sessions(events: Iterable[UsageEvent]) -> dict[str, str]:
    """Classify every session into a shape bucket. Returns ``{session_id: shape}``."""
    totals = session_token_totals(events)
    cutoffs = shape_cutoffs(list(totals.values()))
    return {
        session_id: classify_session_shape(total, cutoffs) for session_id, total in totals.items()
    }


def hour_dow_buckets(
    events: Iterable[UsageEvent],
    timezone: str,
    *,
    cost_fn,
) -> tuple[list[float], list[float]]:
    """Return ``(by_hour[24], by_dow[7])`` cost arrays in local TZ.

    ``cost_fn(event) -> float`` lets callers pick the metric (dollars,
    tokens, events). The function is invoked once per event.
    """
    tz = load_timezone(timezone)
    by_hour = [0.0] * 24
    by_dow = [0.0] * 7
    for event in events:
        local = event.timestamp.astimezone(tz)
        amount = float(cost_fn(event))
        by_hour[local.hour] += amount
        by_dow[local.weekday()] += amount
    return by_hour, by_dow


def session_first_prompt_hash(event: UsageEvent) -> str:
    """Stable opaque hash over the first user message of an event's thread.

    Used by duplicate-session detection. Never leaks raw prompt text in
    JSON output. Returns ``""`` when the thread has no first message.
    """
    seed = event.thread.first_user_message.strip()
    if not seed:
        return ""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return digest[:16]


def prompt_rot_curve(events: list[UsageEvent]) -> list[int]:
    """Return ``uncached_input_tokens`` per event in chronological order
    for a single session. Used by the prompt-rot finder to detect
    growth without re-sorting in the caller."""
    if not events:
        return []
    ordered = sorted(events, key=lambda event: event.timestamp)
    return [event.usage.uncached_input_tokens for event in ordered]


def is_trivial_turn(event: UsageEvent) -> bool:
    """A turn looks 'trivial' when the model wrote little, did no tool
    use, and saw little context. Used by reasoning-waste and
    model-overselection finders."""
    usage = event.usage
    if usage.output_tokens > TRIVIAL_OUTPUT_TOKENS:
        return False
    if usage.uncached_input_tokens > TRIVIAL_INPUT_TOKENS:
        return False
    tool_facts = event.turn_facts
    return not (tool_facts is not None and tool_facts.tool_use_count)


def session_event_groups(events: Iterable[UsageEvent]) -> dict[str, list[UsageEvent]]:
    """Group events by ``session_id``. Sessions with empty id are
    dropped; callers cannot reason about them."""
    groups: dict[str, list[UsageEvent]] = defaultdict(list)
    for event in events:
        if not event.session_id:
            continue
        groups[event.session_id].append(event)
    return dict(groups)


def project_for_event(event: UsageEvent) -> str:
    """Stable project key. Falls back to thread cwd, then 'unknown'."""
    return event.thread.cwd or "unknown"


def daily_buckets(
    events: Iterable[UsageEvent],
    timezone: str,
    *,
    value_fn,
) -> dict[dt.date, float]:
    """Sum ``value_fn(event)`` into local-TZ daily buckets."""
    tz = load_timezone(timezone)
    buckets: dict[dt.date, float] = defaultdict(float)
    for event in events:
        local_date = event.timestamp.astimezone(tz).date()
        buckets[local_date] += float(value_fn(event))
    return dict(buckets)


def per_model_daily_tokens(
    events: Iterable[UsageEvent],
    timezone: str,
) -> dict[str, dict[dt.date, int]]:
    """Sum ``total_tokens`` per ``(model, local_date)``."""
    tz = load_timezone(timezone)
    result: dict[str, dict[dt.date, int]] = defaultdict(lambda: defaultdict(int))
    for event in events:
        if not event.model:
            continue
        local_date = event.timestamp.astimezone(tz).date()
        result[event.model][local_date] += event.usage.total_tokens
    return {model: dict(days) for model, days in result.items()}


__all__ = [
    "SHAPE_LABELS",
    "SHAPE_LARGE",
    "SHAPE_MEDIUM",
    "SHAPE_SMALL",
    "TRIVIAL_INPUT_TOKENS",
    "TRIVIAL_OUTPUT_TOKENS",
    "classify_all_sessions",
    "classify_session_shape",
    "daily_buckets",
    "hour_dow_buckets",
    "is_trivial_turn",
    "per_model_daily_tokens",
    "project_for_event",
    "prompt_rot_curve",
    "session_event_groups",
    "session_first_prompt_hash",
    "session_token_totals",
    "shape_cutoffs",
]
