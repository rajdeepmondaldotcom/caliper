from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from caliper.aggregation import aggregate_total, event_cost
from caliper.intervals import Interval
from caliper.models import Aggregate, LoadResult, RuntimeOptions, UsageEvent, decimal_value
from caliper.output import amount_fields
from caliper.pricing import RateCard
from caliper.render import pricing_status, pricing_warnings
from caliper.timeutil import iso_z


def days_for_interval(interval: Interval) -> int:
    """Round the span of an ``Interval`` to integer days.

    ``build_whatif_report`` takes ``days: int``; the Textual TUI lets
    the user pick an :class:`Interval`. This helper canonicalises one
    into the other. Returns at least ``1`` even for sub-day intervals
    so a what-if simulation always evaluates *some* window.
    """
    seconds = max((interval.end - interval.start).total_seconds(), 0.0)
    return max(int(round(seconds / 86_400.0)), 1)


@dataclass(frozen=True)
class WhatIfTotals:
    actual_cost_usd: Decimal
    hypothetical_cost_usd: Decimal
    cost_usd_delta: Decimal
    cost_usd_pct: float


@dataclass(frozen=True)
class WhatIfReport:
    days: int
    tier: str | None
    model: str | None
    events_evaluated: int
    pricing_status: str
    pricing_warnings: list[str]
    totals: WhatIfTotals | None = None
    noop_message: str = ""

    @property
    def noop(self) -> bool:
        return self.noop_message != ""

    @property
    def label(self) -> str:
        parts = []
        if self.tier:
            parts.append(f"tier={self.tier}")
        if self.model:
            parts.append(f"model={self.model}")
        return ", ".join(parts) or "no-op"

    def json_payload(self) -> dict:
        payload = {
            "days": self.days,
            "hypothetical": {"tier": self.tier, "model": self.model},
        }
        if self.noop:
            payload.update(
                {
                    "noop": True,
                    "message": self.noop_message,
                    "events_evaluated": self.events_evaluated,
                    "pricing_status": self.pricing_status,
                    "pricing_warnings": self.pricing_warnings,
                }
            )
            return payload

        totals = self._require_totals()
        payload.update(
            {
                "actual": {
                    **amount_fields("cost_usd", totals.actual_cost_usd),
                },
                "projected": {
                    **amount_fields("cost_usd", totals.hypothetical_cost_usd),
                },
                "delta": {
                    **amount_fields("cost_usd", totals.cost_usd_delta),
                    "cost_usd_pct": totals.cost_usd_pct,
                },
                "events_evaluated": self.events_evaluated,
                "pricing_status": self.pricing_status,
                "pricing_warnings": self.pricing_warnings,
            }
        )
        return payload

    def records(self) -> list[dict]:
        if self.noop:
            return [
                {
                    "days": self.days,
                    "tier": self.tier or "",
                    "model": self.model or "",
                    "noop": True,
                    "message": self.noop_message,
                    "events_evaluated": self.events_evaluated,
                    "pricing_status": self.pricing_status,
                }
            ]
        totals = self._require_totals()
        return [
            {
                "metric": "cost_usd",
                "actual": totals.actual_cost_usd,
                "projected": totals.hypothetical_cost_usd,
                "delta": totals.cost_usd_delta,
                "pct": totals.cost_usd_pct,
                "pricing_status": self.pricing_status,
            },
        ]

    def _require_totals(self) -> WhatIfTotals:
        if self.totals is None:
            raise ValueError("what-if totals are unavailable for no-op reports")
        return self.totals


def events_in_interval(events, interval: Interval):
    return [event for event in events if interval.start <= event.timestamp < interval.end]


def aggregate_interval(
    events,
    options: RuntimeOptions,
    rate_card: RateCard,
    interval: Interval,
    label: str,
) -> Aggregate:
    filtered = events_in_interval(events, interval)
    result = LoadResult(
        events=filtered,
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )
    return aggregate_total(result, options, label=label, rate_card=rate_card)


def aggregate_interval_by_vendor(
    events,
    options: RuntimeOptions,
    rate_card: RateCard,
    interval: Interval,
    label: str,
) -> dict[str, Aggregate]:
    """Split an interval into per-vendor aggregates."""
    filtered = events_in_interval(events, interval)
    groups: dict[str, list[UsageEvent]] = {}
    for event in filtered:
        groups.setdefault(event.vendor or "unknown", []).append(event)
    out: dict[str, Aggregate] = {}
    for vendor_id, vendor_events in groups.items():
        result = LoadResult(
            events=vendor_events,
            duplicates=0,
            tier_sources={},
            plan_types=set(),
            rate_limit_samples=[],
            warnings=[],
        )
        out[vendor_id] = aggregate_total(
            result, options, label=f"{label} / {vendor_id}", rate_card=rate_card
        )
    return out


def amount_delta(left, right) -> tuple[Any, float]:
    diff = left - right
    pct = float(decimal_value(diff) / decimal_value(right) * Decimal("100")) if right else 0.0
    return diff, pct


def sparse_comparison_warning(agg_a: Aggregate, agg_b: Aggregate) -> str:
    max_events = max(agg_a.totals.events, agg_b.totals.events)
    min_events = min(agg_a.totals.events, agg_b.totals.events)
    if max_events and min_events < max_events * 0.05:
        sparse_side = "A" if agg_a.totals.events == min_events else "B"
        return (
            f"warning: window {sparse_side} has {min_events:,} events; "
            "comparison is not representative"
        )
    return ""


def interval_summary(interval: Interval, agg: Aggregate) -> dict:
    return {
        "label": interval.label,
        "start": iso_z(interval.start),
        "end": iso_z(interval.end),
        **amount_fields("calculated_cost_usd", agg.costs.calculated_cost_usd),
        **amount_fields("cost_usd", agg.costs.cost_usd),
        "events": agg.totals.events,
        "tokens": agg.totals.total_tokens,
        "models": sorted(agg.models),
        "pricing_status": pricing_status(agg),
        "pricing_warnings": pricing_warnings(agg),
    }


def is_whatif_noop(events: list[UsageEvent], *, tier: str | None, model: str | None) -> bool:
    return bool(events) and all(
        (tier is None or event.service_tier == tier) and (model is None or event.model == model)
        for event in events
    )


def calculate_whatif_totals(
    events: list[UsageEvent],
    rate_card: RateCard,
    *,
    tier: str | None,
    model: str | None,
) -> WhatIfTotals:
    actual_cost_usd = Decimal("0")
    hypothetical_cost_usd = Decimal("0")
    for event in events:
        actual, _, _ = event_cost(rate_card, event)
        actual_cost_usd += actual.cost_usd
        hypothetical_event = replace(
            event,
            model=model or event.model,
            service_tier=tier or event.service_tier,
            vendor_reported_cost_usd=None,
        )
        hypothetical, _, _ = event_cost(rate_card, hypothetical_event)
        hypothetical_cost_usd += hypothetical.cost_usd

    cost_usd_delta = hypothetical_cost_usd - actual_cost_usd
    return WhatIfTotals(
        actual_cost_usd=actual_cost_usd,
        hypothetical_cost_usd=hypothetical_cost_usd,
        cost_usd_delta=cost_usd_delta,
        cost_usd_pct=(
            float(cost_usd_delta / actual_cost_usd * Decimal("100")) if actual_cost_usd else 0.0
        ),
    )


def build_whatif_report(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    *,
    days: int,
    tier: str | None,
    model: str | None,
) -> WhatIfReport:
    actual_total = aggregate_total(result, options, rate_card=rate_card)
    actual_status = pricing_status(actual_total)
    actual_warnings = pricing_warnings(actual_total)
    if is_whatif_noop(result.events, tier=tier, model=model):
        label = _whatif_label(tier=tier, model=model)
        return WhatIfReport(
            days=days,
            tier=tier,
            model=model,
            events_evaluated=len(result.events),
            pricing_status=actual_status,
            pricing_warnings=actual_warnings,
            noop_message=f"All {len(result.events):,} events are already at {label}; no change.",
        )
    return WhatIfReport(
        days=days,
        tier=tier,
        model=model,
        events_evaluated=len(result.events),
        pricing_status=actual_status,
        pricing_warnings=actual_warnings,
        totals=calculate_whatif_totals(result.events, rate_card, tier=tier, model=model),
    )


def _whatif_label(*, tier: str | None, model: str | None) -> str:
    parts = []
    if tier:
        parts.append(f"tier={tier}")
    if model:
        parts.append(f"model={model}")
    return ", ".join(parts)
