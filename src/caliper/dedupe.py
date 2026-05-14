from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from caliper.models import UsageEvent


@dataclass(frozen=True)
class EventIdentity:
    strategy: str
    key: tuple[object, ...]


@dataclass(frozen=True)
class DedupeStats:
    duplicates: int = 0
    by_strategy: dict[str, int] = field(default_factory=dict)

    def merged(self, other: DedupeStats) -> DedupeStats:
        strategies = Counter(self.by_strategy)
        strategies.update(other.by_strategy)
        return DedupeStats(
            duplicates=self.duplicates + other.duplicates,
            by_strategy=dict(strategies),
        )


def event_identity(event: UsageEvent) -> EventIdentity | None:
    vendor = event.vendor or "unknown"
    if event.event_id:
        return EventIdentity("event_id", (vendor, event.event_id))
    if event.message_id and event.request_id:
        return EventIdentity("message_request", (vendor, event.message_id, event.request_id))
    if event.request_id:
        return EventIdentity("request_id", (vendor, event.request_id))
    if event.dedupe_key:
        return EventIdentity("dedupe_key", (vendor, event.dedupe_key))
    if event.timestamp and not event.usage.is_zero():
        return EventIdentity(
            "semantic_usage",
            (
                vendor,
                event.timestamp.isoformat(),
                event.session_id,
                event.model,
                event.service_tier,
                event.usage.input_tokens,
                event.usage.cache_creation_input_tokens,
                event.usage.cache_read_input_tokens,
                event.usage.cache_creation_input_1h_tokens,
                event.usage.output_tokens,
                event.usage.reasoning_output_tokens,
                event.usage.total_tokens,
            ),
        )
    return None


def dedupe_usage_events(
    events: list[UsageEvent],
    *,
    enabled: bool = True,
) -> tuple[list[UsageEvent], DedupeStats]:
    if not enabled:
        return events, DedupeStats()

    seen: set[tuple[object, ...]] = set()
    unique: list[UsageEvent] = []
    by_strategy: Counter[str] = Counter()
    for event in events:
        identity = event_identity(event)
        if identity is None:
            unique.append(event)
            continue
        if identity.key in seen:
            by_strategy[identity.strategy] += 1
            continue
        seen.add(identity.key)
        unique.append(event)
    return unique, DedupeStats(duplicates=sum(by_strategy.values()), by_strategy=dict(by_strategy))
