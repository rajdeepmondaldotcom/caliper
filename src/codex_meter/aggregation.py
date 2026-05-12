from __future__ import annotations

from collections.abc import Callable

from codex_meter.models import Aggregate, LoadResult, RuntimeOptions, UsageEvent
from codex_meter.pricing import RateCard
from codex_meter.timeutil import day_key, load_timezone, month_key, week_key


def aggregate_events(
    events: list[UsageEvent],
    key_fn: Callable[[UsageEvent], tuple[str, str]],
    options: RuntimeOptions,
    rate_card: RateCard | None = None,
) -> list[Aggregate]:
    card = rate_card or RateCard.load(options.rates_file, options.pricing_mode)
    aggregates: dict[str, Aggregate] = {}
    for event in events:
        key, label = key_fn(event)
        item = aggregates.setdefault(key, Aggregate(key=key, label=label))
        costs, long_context, unknown_model = card.cost_for(
            event.usage, event.model, event.service_tier
        )
        unknown_tier = event.tier_source in {"current-config", "assumed"}
        item.add_event(event, costs, long_context, unknown_model, unknown_tier)
    return sorted(aggregates.values(), key=lambda item: item.key)


def aggregate_total(
    result: LoadResult,
    options: RuntimeOptions,
    label: str = "Total",
    rate_card: RateCard | None = None,
) -> Aggregate:
    items = aggregate_events(
        result.events, lambda _event: ("total", label), options, rate_card=rate_card
    )
    return items[0] if items else Aggregate(key="total", label=label)


def aggregate_daily(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    tz = load_timezone(options.timezone)
    return aggregate_events(
        result.events,
        lambda event: (day_key(event.timestamp, tz), day_key(event.timestamp, tz)),
        options,
        rate_card=rate_card,
    )


def aggregate_weekly(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    tz = load_timezone(options.timezone)
    return aggregate_events(
        result.events,
        lambda event: (week_key(event.timestamp, tz), week_key(event.timestamp, tz)),
        options,
        rate_card=rate_card,
    )


def aggregate_monthly(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    tz = load_timezone(options.timezone)
    return aggregate_events(
        result.events,
        lambda event: (month_key(event.timestamp, tz), month_key(event.timestamp, tz)),
        options,
        rate_card=rate_card,
    )


def aggregate_sessions(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    def key(event: UsageEvent) -> tuple[str, str]:
        local_time = event.timestamp.astimezone(load_timezone(options.timezone)).strftime(
            "%Y-%m-%d %H:%M"
        )
        if options.show_prompts:
            title = event.thread.title or event.thread.first_user_message or event.session_id
        else:
            title = event.session_id
        return event.session_id, f"{local_time} | {title}"

    return sorted(
        aggregate_events(result.events, key, options, rate_card=rate_card),
        key=lambda item: item.costs.adjusted_credits,
        reverse=True,
    )


def aggregate_projects(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    def key(event: UsageEvent) -> tuple[str, str]:
        project = event.thread.cwd or "Unknown Project"
        return project, project

    return sorted(
        aggregate_events(result.events, key, options, rate_card=rate_card),
        key=lambda item: item.costs.adjusted_credits,
        reverse=True,
    )


def aggregate_model_mode(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    return sorted(
        aggregate_events(
            result.events,
            lambda event: (
                f"{event.model}\0{event.service_tier}",
                f"{event.model or 'unknown model'} / {event.service_tier or 'unknown tier'}",
            ),
            options,
            rate_card=rate_card,
        ),
        key=lambda item: item.costs.adjusted_credits,
        reverse=True,
    )
