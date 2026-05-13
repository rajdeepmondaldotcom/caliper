from __future__ import annotations

import datetime as dt

from caliper.aggregation import aggregate_total
from caliper.models import LoadResult, RuntimeOptions
from caliper.parser import load_usage
from caliper.pricing import load_rate_card
from caliper.timeutil import local_timezone
from caliper.windows import compute_window_state


def build_prometheus_snapshot(options: RuntimeOptions):
    """Construct a Prometheus MetricsSnapshot from a freshly loaded usage window."""
    from caliper.prom_export import MetricsSnapshot

    result = load_usage(options)
    rate_card = load_rate_card(options)
    now = dt.datetime.now(tz=local_timezone())
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_events = [event for event in result.events if event.timestamp >= today_start]
    today_result = LoadResult(
        events=today_events,
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
    )
    totals = aggregate_total(today_result, options, label="today", rate_card=rate_card)
    primary = compute_window_state(result.credit_samples, now, "primary")
    secondary = compute_window_state(result.credit_samples, now, "secondary")

    return MetricsSnapshot(
        credits_used=float(totals.costs.adjusted_credits),
        burn_per_hour=primary.burn_rate_per_hour if primary.burn_rate_per_hour else 0.0,
        primary_window_percent=primary.used_percent if primary.used_percent is not None else 0.0,
        secondary_window_percent=(
            secondary.used_percent if secondary.used_percent is not None else 0.0
        ),
        events_total=totals.totals.events,
        long_context_events_total=totals.long_context_events,
        tokens_total=_token_totals(today_events),
    )


def _token_totals(events) -> dict[tuple[str, str, str], int]:
    tokens: dict[tuple[str, str, str], int] = {}
    for event in events:
        model = event.model or "unknown"
        tier = event.service_tier or "unknown"
        _add_token_total(tokens, model, tier, "input", event.usage.input_tokens)
        _add_token_total(tokens, model, tier, "cached", event.usage.cached_input_tokens)
        _add_token_total(tokens, model, tier, "output", event.usage.output_tokens)
        _add_token_total(tokens, model, tier, "reasoning", event.usage.reasoning_output_tokens)
    return tokens


def _add_token_total(
    tokens: dict[tuple[str, str, str], int],
    model: str,
    tier: str,
    kind: str,
    amount: int,
) -> None:
    key = (model, tier, kind)
    tokens[key] = tokens.get(key, 0) + int(amount)
