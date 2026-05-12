from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from codex_meter.models import Aggregate, LoadResult, RuntimeOptions, UsageEvent
from codex_meter.pricing import estimate_event_cost
from codex_meter.timeutil import day_key, load_timezone, month_key, week_key


def aggregate_events(
    events: list[UsageEvent],
    key_fn: Callable[[UsageEvent], tuple[str, str]],
    options: RuntimeOptions,
) -> list[Aggregate]:
    aggregates: dict[str, Aggregate] = {}
    for event in events:
        key, label = key_fn(event)
        item = aggregates.setdefault(key, Aggregate(key=key, label=label))
        costs, long_context, unknown_model = estimate_event_cost(
            event.usage,
            event.model,
            event.service_tier,
            options.pricing_mode,
            options.rates_file,
        )
        unknown_tier = event.tier_source in {"current-config", "assumed"}
        item.add_event(event, costs, long_context, unknown_model, unknown_tier)
    return sorted(aggregates.values(), key=lambda item: item.key)


def aggregate_total(result: LoadResult, options: RuntimeOptions, label: str = "Total") -> Aggregate:
    items = aggregate_events(result.events, lambda _event: ("total", label), options)
    total = items[0] if items else Aggregate(key="total", label=label)
    return total


def aggregate_daily(result: LoadResult, options: RuntimeOptions) -> list[Aggregate]:
    tz = load_timezone(options.timezone)
    return aggregate_events(
        result.events,
        lambda event: (day_key(event.timestamp, tz), day_key(event.timestamp, tz)),
        options,
    )


def aggregate_weekly(result: LoadResult, options: RuntimeOptions) -> list[Aggregate]:
    tz = load_timezone(options.timezone)
    return aggregate_events(
        result.events,
        lambda event: (week_key(event.timestamp, tz), week_key(event.timestamp, tz)),
        options,
    )


def aggregate_monthly(result: LoadResult, options: RuntimeOptions) -> list[Aggregate]:
    tz = load_timezone(options.timezone)
    return aggregate_events(
        result.events,
        lambda event: (month_key(event.timestamp, tz), month_key(event.timestamp, tz)),
        options,
    )


def aggregate_sessions(result: LoadResult, options: RuntimeOptions) -> list[Aggregate]:
    def key(event: UsageEvent) -> tuple[str, str]:
        local_time = event.timestamp.astimezone(load_timezone(options.timezone)).strftime(
            "%Y-%m-%d %H:%M"
        )
        title = event.thread.title or event.thread.first_user_message or event.session_id
        return event.session_id, f"{local_time} | {title}"

    return sorted(
        aggregate_events(result.events, key, options),
        key=lambda item: item.costs.adjusted_credits,
        reverse=True,
    )


def aggregate_projects(result: LoadResult, options: RuntimeOptions) -> list[Aggregate]:
    def key(event: UsageEvent) -> tuple[str, str]:
        project = event.thread.cwd or "Unknown Project"
        return project, project

    return sorted(
        aggregate_events(result.events, key, options),
        key=lambda item: item.costs.adjusted_credits,
        reverse=True,
    )


def aggregate_model_mode(result: LoadResult, options: RuntimeOptions) -> list[Aggregate]:
    return sorted(
        aggregate_events(
            result.events,
            lambda event: (
                f"{event.model}\0{event.service_tier}",
                f"{event.model or 'unknown model'} / {event.service_tier or 'unknown tier'}",
            ),
            options,
        ),
        key=lambda item: item.costs.adjusted_credits,
        reverse=True,
    )


def window_label(start: dt.datetime, end: dt.datetime, tzname: str) -> str:
    tz = load_timezone(tzname)
    start_label = start.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    end_label = end.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    return f"{start_label} to {end_label}"
