"""Threaded data workers that keep the UI responsive during loads.

Each worker is a small wrapper over an existing pure module from the
Caliper core. The TUI never re-implements aggregation, pricing, or
window state — only orchestrates them and posts the results back via
:mod:`caliper.tui.messages`.
"""

from __future__ import annotations

import datetime as dt

from caliper.aggregation import (
    aggregate_many,
    aggregate_overview_windows,
    budget_impact_sort_key,
)
from caliper.humanize import session_display_label
from caliper.insights import build_insights_from
from caliper.models import UNKNOWN_PROJECT, LoadResult, RuntimeOptions, UsageEvent
from caliper.parser import load_usage
from caliper.pricing import RateCard, load_rate_card
from caliper.timeutil import day_key, load_timezone, local_timezone, month_key, week_key
from caliper.tui.messages import WorkerCancelled
from caliper.tui.progress import TextualParseProgress
from caliper.windows import compute_window_state


def run_load(
    options: RuntimeOptions, progress: TextualParseProgress
) -> tuple[LoadResult, RateCard]:
    """Pull usage and the rate card off disk on the worker thread."""
    try:
        result = load_usage(options, progress=progress)
    except WorkerCancelled:
        raise
    card = load_rate_card(options)
    return result, card


def build_overview(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    *,
    now: dt.datetime | None = None,
) -> dict:
    """Produce all TUI aggregates while pricing each event as few times as possible."""
    when = now or dt.datetime.now(tz=local_timezone())
    windows, total = aggregate_overview_windows(
        result,
        options,
        [
            ("Last 7 days", when - dt.timedelta(days=7)),
            ("Last 30 days", when - dt.timedelta(days=30)),
            ("Last 90 days", when - dt.timedelta(days=90)),
        ],
        rate_card=rate_card,
        detailed=False,
    )
    daily, weekly, monthly, sessions, projects, models = aggregate_many(
        result.events,
        _tui_key_functions(options),
        options,
        rate_card=rate_card,
    )
    sessions = sorted(sessions, key=budget_impact_sort_key)
    projects = sorted(projects, key=budget_impact_sort_key)
    models = sorted(models, key=budget_impact_sort_key)
    insights = build_insights_from(
        result=result,
        rate_card=rate_card,
        total=total,
        projects=projects,
        daily=daily,
    )
    primary = compute_window_state(result.rate_limit_samples, when, "primary")
    secondary = compute_window_state(result.rate_limit_samples, when, "secondary")
    return {
        "overview_windows": tuple(windows),
        "overview_total": total,
        "daily": tuple(daily),
        "weekly": tuple(weekly),
        "monthly": tuple(monthly),
        "sessions": tuple(sessions),
        "projects": tuple(projects),
        "models": tuple(models),
        "insights": tuple(insights),
        "primary_window": primary,
        "secondary_window": secondary,
    }


def _tui_key_functions(options: RuntimeOptions):
    tz = load_timezone(options.timezone)

    def daily_key(event: UsageEvent) -> tuple[str, str]:
        day = day_key(event.timestamp, tz)
        return day, day

    def weekly_key(event: UsageEvent) -> tuple[str, str]:
        week = week_key(event.timestamp, tz, options.start_of_week)
        return week, week

    def monthly_key(event: UsageEvent) -> tuple[str, str]:
        month = month_key(event.timestamp, tz)
        return month, month

    def session_key(event: UsageEvent) -> tuple[str, str]:
        return event.session_id, session_display_label(
            event,
            options.timezone,
            include_title=options.show_prompts,
        )

    def project_key(event: UsageEvent) -> tuple[str, str]:
        project = event.thread.cwd or UNKNOWN_PROJECT
        return project, project

    def model_key(event: UsageEvent) -> tuple[str, str]:
        return (
            f"{event.model}\0{event.service_tier}",
            f"{event.model or 'unknown model'} / {event.service_tier or 'unknown tier'}",
        )

    return [daily_key, weekly_key, monthly_key, session_key, project_key, model_key]
