from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from caliper.models import RateLimitSample, UsageEvent


@dataclass(frozen=True)
class EventIdentity:
    strategy: str
    key: tuple[object, ...]

    @property
    def fingerprint(self) -> tuple[object, ...]:
        return (self.strategy, *self.key)


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


def event_identities(event: UsageEvent) -> tuple[EventIdentity, ...]:
    vendor = event.vendor or "unknown"
    identities: list[EventIdentity] = []
    if event.event_id:
        identities.append(EventIdentity("event_id", (vendor, event.session_id, event.event_id)))
    if event.message_id and event.request_id:
        identities.append(
            EventIdentity(
                "message_request",
                (vendor, event.session_id, event.message_id, event.request_id),
            )
        )
    if event.request_id and not (event.event_id or event.message_id):
        identities.append(
            EventIdentity(
                "request_id",
                (vendor, event.session_id, event.request_id, *_semantic_usage_key(event)),
            )
        )
    if event.dedupe_key:
        identities.append(EventIdentity("dedupe_key", (vendor, event.session_id, event.dedupe_key)))
    if not _has_vendor_identity(event) and event.timestamp and not event.usage.is_zero():
        identities.append(
            EventIdentity(
                "semantic_usage",
                (vendor, event.session_id, *_semantic_usage_key(event)),
            )
        )
    return tuple(identities)


def _semantic_usage_key(event: UsageEvent) -> tuple[object, ...]:
    return (
        event.timestamp.isoformat(),
        event.model,
        event.service_tier,
        event.thread.cwd,
        event.usage_source,
        _stable_value(event.vendor_reported_cost_usd),
        event.usage.input_tokens,
        event.usage.cache_creation_input_tokens,
        event.usage.cache_read_input_tokens,
        event.usage.cache_creation_input_1h_tokens,
        event.usage.output_tokens,
        event.usage.reasoning_output_tokens,
        event.usage.total_tokens,
    )


def _has_vendor_identity(event: UsageEvent) -> bool:
    return bool(event.event_id or event.message_id or event.request_id)


def event_identity(event: UsageEvent) -> EventIdentity | None:
    identities = event_identities(event)
    return identities[0] if identities else None


def rate_limit_sample_identity(sample: RateLimitSample) -> EventIdentity | None:
    if sample.timestamp is None:
        return None
    vendor = sample.vendor or "unknown"
    return EventIdentity(
        "rate_limit_sample",
        (
            vendor,
            sample.session_id,
            sample.timestamp.isoformat(),
            sample.plan_type,
            sample.limit_id,
            sample.limit_name,
            _stable_value(sample.primary_used_percent),
            _stable_value(sample.primary_window_minutes),
            _stable_value(sample.primary_resets_at),
            _stable_value(sample.secondary_used_percent),
            _stable_value(sample.secondary_window_minutes),
            _stable_value(sample.secondary_resets_at),
            sample.rate_limit_reached_type,
        ),
    )


def _stable_value(value: object) -> object:
    if value is None:
        return None
    return str(value)


def _dedupe_by_identities(
    items: list,
    identity_fn,
) -> tuple[list, DedupeStats]:
    seen: set[tuple[object, ...]] = set()
    unique: list = []
    by_strategy: Counter[str] = Counter()
    for item in items:
        identities = identity_fn(item)
        if identities is None:
            item_identities = ()
        elif isinstance(identities, EventIdentity):
            item_identities = (identities,)
        else:
            item_identities = tuple(identities)
        if not item_identities:
            unique.append(item)
            continue
        matched = next(
            (identity for identity in item_identities if identity.fingerprint in seen),
            None,
        )
        if matched is not None:
            by_strategy[matched.strategy] += 1
            continue
        for identity in item_identities:
            seen.add(identity.fingerprint)
        unique.append(item)
    return unique, DedupeStats(duplicates=sum(by_strategy.values()), by_strategy=dict(by_strategy))


def dedupe_rate_limit_samples(
    samples: list[RateLimitSample],
    *,
    enabled: bool = True,
) -> tuple[list[RateLimitSample], DedupeStats]:
    del enabled
    return _dedupe_by_identities(samples, rate_limit_sample_identity)


def dedupe_usage_events(
    events: list[UsageEvent],
    *,
    enabled: bool = True,
) -> tuple[list[UsageEvent], DedupeStats]:
    del enabled
    return _dedupe_by_identities(events, event_identities)
