from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from caliper.aggregation import aggregate_total
from caliper.models import LoadResult, RuntimeOptions, UsageEvent
from caliper.pricing import RateCard
from caliper.timeutil import iso_z

DEFAULT_SESSION_LENGTH_HOURS = 5
RECENT_DAYS = 3


@dataclass(frozen=True)
class UsageBlock:
    id: str
    start_time: dt.datetime
    end_time: dt.datetime
    actual_end_time: dt.datetime | None
    is_active: bool
    is_gap: bool
    events: tuple[UsageEvent, ...]
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int
    api_dollars: Decimal
    models: tuple[str, ...]


def build_blocks(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    *,
    session_length_hours: float = DEFAULT_SESSION_LENGTH_HOURS,
    now: dt.datetime | None = None,
) -> list[UsageBlock]:
    events = sorted(result.events, key=lambda event: event.timestamp)
    if not events:
        return []
    duration = dt.timedelta(hours=session_length_hours)
    now = now or dt.datetime.now(tz=dt.UTC)
    blocks: list[UsageBlock] = []
    current_start: dt.datetime | None = None
    current_events: list[UsageEvent] = []
    for event in events:
        if current_start is None:
            current_start = _floor_to_hour(event.timestamp)
            current_events = [event]
            continue
        last = current_events[-1]
        if (
            event.timestamp - current_start > duration
            or event.timestamp - last.timestamp > duration
        ):
            blocks.append(
                _create_block(current_start, current_events, options, rate_card, duration, now)
            )
            gap = _create_gap(last.timestamp, event.timestamp, duration)
            if gap is not None:
                blocks.append(gap)
            current_start = _floor_to_hour(event.timestamp)
            current_events = [event]
        else:
            current_events.append(event)
    if current_start is not None and current_events:
        blocks.append(
            _create_block(current_start, current_events, options, rate_card, duration, now)
        )
    return blocks


def block_payload(block: UsageBlock, token_limit: int | None = None) -> dict:
    burn_rate = calculate_burn_rate(block)
    projection = project_block_usage(block, burn_rate)
    item = {
        "id": block.id,
        "startTime": iso_z(block.start_time),
        "endTime": iso_z(block.end_time),
        "actualEndTime": iso_z(block.actual_end_time) if block.actual_end_time else None,
        "isActive": block.is_active,
        "isGap": block.is_gap,
        "entries": len(block.events),
        "tokenCounts": {
            "inputTokens": block.input_tokens,
            "outputTokens": block.output_tokens,
            "cacheCreationInputTokens": block.cache_creation_tokens,
            "cacheReadInputTokens": block.cache_read_tokens,
        },
        "totalTokens": block.total_tokens,
        "costUSD": float(block.api_dollars),
        "models": list(block.models),
        "burnRate": burn_rate,
        "projection": projection,
    }
    if token_limit is not None and token_limit > 0:
        item["tokenLimitStatus"] = {
            "limit": token_limit,
            "percent": block.total_tokens / token_limit * 100,
            "exceeded": block.total_tokens > token_limit,
        }
    return item


def filter_recent_blocks(
    blocks: list[UsageBlock], now: dt.datetime | None = None
) -> list[UsageBlock]:
    now = now or dt.datetime.now(tz=dt.UTC)
    cutoff = now - dt.timedelta(days=RECENT_DAYS)
    return [block for block in blocks if block.start_time >= cutoff or block.is_active]


def calculate_burn_rate(block: UsageBlock) -> dict | None:
    if block.is_gap or len(block.events) < 2:
        return None
    first = block.events[0].timestamp
    last = block.events[-1].timestamp
    minutes = (last - first).total_seconds() / 60
    if minutes <= 0:
        return None
    return {
        "tokensPerMinute": block.total_tokens / minutes,
        "tokensPerMinuteForIndicator": (block.input_tokens + block.output_tokens) / minutes,
        "costPerHour": float(block.api_dollars) / minutes * 60,
    }


def project_block_usage(block: UsageBlock, burn_rate: dict | None = None) -> dict | None:
    if not block.is_active or block.is_gap:
        return None
    burn_rate = burn_rate or calculate_burn_rate(block)
    if burn_rate is None:
        return None
    now = dt.datetime.now(tz=dt.UTC)
    remaining_minutes = max(0, (block.end_time - now).total_seconds() / 60)
    projected_tokens = block.total_tokens + burn_rate["tokensPerMinute"] * remaining_minutes
    projected_cost = float(block.api_dollars) + burn_rate["costPerHour"] / 60 * remaining_minutes
    return {
        "totalTokens": round(projected_tokens),
        "totalCost": round(projected_cost, 2),
        "remainingMinutes": round(remaining_minutes),
    }


def _create_block(
    start: dt.datetime,
    events: list[UsageEvent],
    options: RuntimeOptions,
    rate_card: RateCard,
    duration: dt.timedelta,
    now: dt.datetime,
) -> UsageBlock:
    end = start + duration
    actual_end = events[-1].timestamp if events else start
    scoped = LoadResult(
        events=list(events),
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
    )
    total = aggregate_total(scoped, options, rate_card=rate_card)
    return UsageBlock(
        id=iso_z(start),
        start_time=start,
        end_time=end,
        actual_end_time=actual_end,
        is_active=now - actual_end < duration and now < end,
        is_gap=False,
        events=tuple(events),
        input_tokens=total.totals.uncached_input_tokens,
        output_tokens=total.totals.output_tokens,
        cache_creation_tokens=(
            total.totals.cache_creation_input_tokens + total.totals.cache_creation_input_1h_tokens
        ),
        cache_read_tokens=total.totals.cache_read_input_tokens,
        total_tokens=total.totals.total_tokens,
        api_dollars=total.costs.api_dollars,
        models=tuple(sorted(total.models)),
    )


def _create_gap(
    last_activity: dt.datetime, next_activity: dt.datetime, duration: dt.timedelta
) -> UsageBlock | None:
    if next_activity - last_activity <= duration:
        return None
    start = last_activity + duration
    return UsageBlock(
        id=f"gap-{iso_z(start)}",
        start_time=start,
        end_time=next_activity,
        actual_end_time=None,
        is_active=False,
        is_gap=True,
        events=(),
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        total_tokens=0,
        api_dollars=Decimal("0"),
        models=(),
    )


def _floor_to_hour(value: dt.datetime) -> dt.datetime:
    return value.astimezone(dt.UTC).replace(minute=0, second=0, microsecond=0)
