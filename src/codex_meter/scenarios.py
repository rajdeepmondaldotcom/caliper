from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from codex_meter.aggregation import aggregate_total
from codex_meter.intervals import Interval
from codex_meter.models import Aggregate, LoadResult, RuntimeOptions, UsageEvent, decimal_value
from codex_meter.output import amount_fields
from codex_meter.pricing import RateCard
from codex_meter.render import pricing_status, pricing_warnings
from codex_meter.timeutil import iso_z


@dataclass(frozen=True)
class WhatIfTotals:
    actual_credits: Decimal
    actual_dollars: Decimal
    hypothetical_credits: Decimal
    hypothetical_dollars: Decimal
    credit_delta: Decimal
    dollar_delta: Decimal
    credit_pct: float
    dollar_pct: float


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
                    **amount_fields("credits", totals.actual_credits),
                    **amount_fields("api_dollars", totals.actual_dollars),
                },
                "projected": {
                    **amount_fields("credits", totals.hypothetical_credits),
                    **amount_fields("api_dollars", totals.hypothetical_dollars),
                },
                "delta": {
                    **amount_fields("credits", totals.credit_delta),
                    "credits_pct": totals.credit_pct,
                    **amount_fields("api_dollars", totals.dollar_delta),
                    "api_dollars_pct": totals.dollar_pct,
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
                "metric": "credits",
                "actual": totals.actual_credits,
                "projected": totals.hypothetical_credits,
                "delta": totals.credit_delta,
                "pct": totals.credit_pct,
                "pricing_status": self.pricing_status,
            },
            {
                "metric": "api_dollars",
                "actual": totals.actual_dollars,
                "projected": totals.hypothetical_dollars,
                "delta": totals.dollar_delta,
                "pct": totals.dollar_pct,
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
        credit_samples=[],
        warnings=[],
    )
    return aggregate_total(result, options, label=label, rate_card=rate_card)


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
        **amount_fields("credits", agg.costs.adjusted_credits),
        **amount_fields("standard_credits", agg.costs.standard_credits),
        **amount_fields("api_dollars", agg.costs.api_dollars),
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
    actual_credits = Decimal("0")
    actual_dollars = Decimal("0")
    hypothetical_credits = Decimal("0")
    hypothetical_dollars = Decimal("0")
    for event in events:
        actual, _, _ = rate_card.cost_for(event.usage, event.model, event.service_tier)
        actual_credits += actual.adjusted_credits
        actual_dollars += actual.api_dollars
        hypothetical, _, _ = rate_card.cost_for(
            event.usage,
            model or event.model,
            tier or event.service_tier,
        )
        hypothetical_credits += hypothetical.adjusted_credits
        hypothetical_dollars += hypothetical.api_dollars

    credit_delta = hypothetical_credits - actual_credits
    dollar_delta = hypothetical_dollars - actual_dollars
    return WhatIfTotals(
        actual_credits=actual_credits,
        actual_dollars=actual_dollars,
        hypothetical_credits=hypothetical_credits,
        hypothetical_dollars=hypothetical_dollars,
        credit_delta=credit_delta,
        dollar_delta=dollar_delta,
        credit_pct=float(credit_delta / actual_credits * Decimal("100")) if actual_credits else 0.0,
        dollar_pct=float(dollar_delta / actual_dollars * Decimal("100")) if actual_dollars else 0.0,
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
