from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from caliper.models import (
    UNKNOWN_PROJECT,
    VENDOR_OPENAI_CODEX,
    Aggregate,
    CostTotals,
    LoadResult,
    RuntimeOptions,
    UsageEvent,
)
from caliper.pricing import RateCard, load_rate_card
from caliper.timeutil import day_key, load_timezone, month_key, week_key


def aggregate_events(
    events: list[UsageEvent],
    key_fn: Callable[[UsageEvent], tuple[str, str]],
    options: RuntimeOptions,
    rate_card: RateCard | None = None,
) -> list[Aggregate]:
    return aggregate_many(events, [key_fn], options, rate_card=rate_card)[0]


def aggregate_many(
    events: list[UsageEvent],
    key_fns: list[Callable[[UsageEvent], tuple[str, str]]],
    options: RuntimeOptions,
    rate_card: RateCard | None = None,
) -> list[list[Aggregate]]:
    card = rate_card or load_rate_card(options)
    aggregate_sets: list[dict[str, Aggregate]] = [{} for _ in key_fns]
    for event in events:
        costs, long_context, unknown_model = event_cost(card, event)
        cache_savings = event_cache_savings(card, event)
        unknown_tier = event.tier_source in {"current-config", "assumed"}
        for aggregates, key_fn in zip(aggregate_sets, key_fns, strict=True):
            key, label = key_fn(event)
            item = aggregates.setdefault(key, Aggregate(key=key, label=label))
            item.add_event(event, costs, cache_savings, long_context, unknown_model, unknown_tier)
    return [sorted(aggregates.values(), key=lambda item: item.key) for aggregates in aggregate_sets]


def event_cost(card: RateCard, event: UsageEvent):
    cache_key = _event_cache_key(event)
    cached = card._event_cost_cache.get(cache_key)
    if cached is not None:
        return cached
    if event.vendor_reported_api_dollars is not None:
        result = (
            CostTotals(
                api_dollars=event.vendor_reported_api_dollars,
                vendor_reported_events=1,
            ),
            False,
            False,
        )
    else:
        result = _event_scoped_cost(
            card.cost_for(event.usage, event.model, event.service_tier),
            event,
        )
    card._event_cost_cache[cache_key] = result
    return result


def event_cache_savings(card: RateCard, event: UsageEvent) -> CostTotals:
    cache_key = _event_cache_key(event)
    cached = card._event_cache_savings_cache.get(cache_key)
    if cached is not None:
        return cached
    result = _event_scoped_cost_totals(
        card.cache_savings_for(event.usage, event.model, event.service_tier),
        event,
    )
    card._event_cache_savings_cache[cache_key] = result
    return result


def _event_scoped_cost(
    result: tuple[CostTotals, bool, bool], event: UsageEvent
) -> tuple[CostTotals, bool, bool]:
    costs, long_context, unknown_model = result
    return _event_scoped_cost_totals(costs, event), long_context, unknown_model


def _event_scoped_cost_totals(costs: CostTotals, event: UsageEvent) -> CostTotals:
    if event.vendor == VENDOR_OPENAI_CODEX:
        return costs
    if (
        costs.standard_credits == 0
        and costs.adjusted_credits == 0
        and costs.credit_unpriced_events == 0
    ):
        return costs
    return CostTotals(
        api_dollars=costs.api_dollars,
        standard_credits=0,
        adjusted_credits=0,
        api_unpriced_events=costs.api_unpriced_events,
        credit_unpriced_events=0,
        estimated_events=costs.estimated_events,
        ambiguous_reasoning_events=costs.ambiguous_reasoning_events,
        local_override_events=costs.local_override_events,
        vendor_reported_events=costs.vendor_reported_events,
    )


def _event_cache_key(event: UsageEvent) -> tuple:
    return (
        event.timestamp,
        event.path,
        event.session_id,
        event.usage.input_tokens,
        event.usage.cache_creation_input_tokens,
        event.usage.cache_read_input_tokens,
        event.usage.cache_creation_input_1h_tokens,
        event.usage.output_tokens,
        event.usage.reasoning_output_tokens,
        event.usage.total_tokens,
        event.model,
        event.service_tier,
        event.vendor,
        event.vendor_reported_api_dollars,
    )


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


def aggregate_overview_windows(
    result: LoadResult,
    options: RuntimeOptions,
    windows: list[tuple[str, dt.datetime]],
    rate_card: RateCard | None = None,
    *,
    detailed: bool = True,
) -> tuple[list[Aggregate], Aggregate]:
    card = rate_card or load_rate_card(options)
    rows = [Aggregate(key="total", label=label) for label, _start in windows]
    total = Aggregate(key="total", label="Total")
    for event in result.events:
        costs, long_context, unknown_model = event_cost(card, event)
        cache_savings = event_cache_savings(card, event)
        unknown_tier = event.tier_source in {"current-config", "assumed"}
        add = _add_detailed_event if detailed else _add_summary_event
        add(total, event, costs, cache_savings, long_context, unknown_model, unknown_tier)
        for row, (_label, start) in zip(rows, windows, strict=True):
            if start <= event.timestamp < options.end:
                add(row, event, costs, cache_savings, long_context, unknown_model, unknown_tier)
    return rows, total


def _add_detailed_event(
    item: Aggregate,
    event: UsageEvent,
    costs: CostTotals,
    cache_savings: CostTotals,
    long_context: bool,
    unknown_model: bool,
    unknown_tier: bool,
) -> None:
    item.add_event(event, costs, cache_savings, long_context, unknown_model, unknown_tier)


def _add_summary_event(
    item: Aggregate,
    event: UsageEvent,
    costs: CostTotals,
    cache_savings: CostTotals,
    long_context: bool,
    unknown_model: bool,
    unknown_tier: bool,
) -> None:
    from caliper.pricing import model_vendor as _model_vendor

    item.totals.add_usage(event.usage)
    item.costs.add(costs)
    item.cache_savings.add(cache_savings)
    if event.model:
        item.models.add(event.model)
        item.model_vendors.add(_model_vendor(event.model))
    if event.vendor:
        item.vendors.add(event.vendor)
    if event.service_tier:
        item.service_tiers.add(event.service_tier)
    if event.plan_type:
        item.plan_types.add(event.plan_type)
    if event.usage_source:
        item.usage_sources.add(event.usage_source)
    if event.model_source:
        item.model_sources.add(event.model_source)
    item.long_context_events += int(long_context)
    item.unknown_model_events += int(unknown_model)
    item.unknown_tier_events += int(unknown_tier)
    item.fallback_model_events += int(event.model_is_fallback)


def aggregate_daily(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    tz = load_timezone(options.timezone)

    def key(event: UsageEvent) -> tuple[str, str]:
        day = day_key(event.timestamp, tz)
        return day, day

    return aggregate_events(
        result.events,
        key,
        options,
        rate_card=rate_card,
    )


def aggregate_daily_instances(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    tz = load_timezone(options.timezone)

    def key(event: UsageEvent) -> tuple[str, str]:
        day = day_key(event.timestamp, tz)
        project = event.thread.cwd or UNKNOWN_PROJECT
        return f"{day}\0{project}", f"{day} / {project}"

    return aggregate_events(result.events, key, options, rate_card=rate_card)


def aggregate_weekly(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    tz = load_timezone(options.timezone)

    def key(event: UsageEvent) -> tuple[str, str]:
        week = week_key(event.timestamp, tz, options.start_of_week)
        return week, week

    return aggregate_events(
        result.events,
        key,
        options,
        rate_card=rate_card,
    )


def aggregate_monthly(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    tz = load_timezone(options.timezone)

    def key(event: UsageEvent) -> tuple[str, str]:
        month = month_key(event.timestamp, tz)
        return month, month

    return aggregate_events(
        result.events,
        key,
        options,
        rate_card=rate_card,
    )


def aggregate_sessions(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    tz = load_timezone(options.timezone)

    def key(event: UsageEvent) -> tuple[str, str]:
        local_time = event.timestamp.astimezone(tz).strftime("%Y-%m-%d %H:%M")
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
        project = event.thread.cwd or UNKNOWN_PROJECT
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


def aggregate_vendors(
    result: LoadResult, options: RuntimeOptions, rate_card: RateCard | None = None
) -> list[Aggregate]:
    return sorted(
        aggregate_events(
            result.events,
            lambda event: (event.vendor or "unknown", event.vendor or "unknown"),
            options,
            rate_card=rate_card,
        ),
        key=lambda item: item.costs.api_dollars,
        reverse=True,
    )
