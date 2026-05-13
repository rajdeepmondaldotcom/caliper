"""Threaded data workers that keep the UI responsive during loads.

Each worker is a small wrapper over an existing pure module from the
Caliper core. The TUI never re-implements aggregation, pricing, or
window state — only orchestrates them and posts the results back via
:mod:`caliper.tui.messages`.
"""

from __future__ import annotations

import datetime as dt

from caliper.aggregation import (
    aggregate_daily,
    aggregate_model_mode,
    aggregate_monthly,
    aggregate_overview_windows,
    aggregate_projects,
    aggregate_sessions,
    aggregate_weekly,
)
from caliper.insights import build_insights_from
from caliper.models import LoadResult, RuntimeOptions
from caliper.parser import load_usage
from caliper.pricing import RateCard, load_rate_card
from caliper.timeutil import local_timezone
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
    """Produce every aggregate the Home screen needs in one batch.

    Returned dict carries plain lists of frozen / mutable dataclasses;
    callers may convert to tuples when stashing on ``AppSnapshot``.
    """
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
    daily = aggregate_daily(result, options, rate_card=rate_card)
    weekly = aggregate_weekly(result, options, rate_card=rate_card)
    monthly = aggregate_monthly(result, options, rate_card=rate_card)
    sessions = aggregate_sessions(result, options, rate_card=rate_card)
    projects = aggregate_projects(result, options, rate_card=rate_card)
    models = aggregate_model_mode(result, options, rate_card=rate_card)
    insights = build_insights_from(
        result=result,
        rate_card=rate_card,
        total=total,
        projects=projects,
        daily=daily,
    )
    primary = compute_window_state(result.credit_samples, when, "primary")
    secondary = compute_window_state(result.credit_samples, when, "secondary")
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
