from __future__ import annotations

from dataclasses import asdict, dataclass

from codex_meter.aggregation import aggregate_daily, aggregate_projects, aggregate_total
from codex_meter.models import CostTotals, LoadResult, RuntimeOptions
from codex_meter.pricing import RateCard


@dataclass(frozen=True)
class Insight:
    severity: str
    title: str
    detail: str
    action: str


def build_insights(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard | None = None,
) -> list[Insight]:
    card = rate_card or RateCard.load(options.rates_file, options.pricing_mode)
    insights: list[Insight] = []
    total = aggregate_total(result, options, rate_card=card)

    if total.totals.input_tokens:
        cache_ratio = total.totals.cached_input_tokens / total.totals.input_tokens
        savings = cache_savings(result, card)
        if total.totals.cached_input_tokens:
            insights.append(
                Insight(
                    severity="info",
                    title="High cache reuse" if cache_ratio >= 0.5 else "Low cache reuse",
                    detail=(
                        f"{cache_ratio:.1%} of input tokens were served from cache, "
                        f"saving about {savings.adjusted_credits:,.2f} credits and "
                        f"${savings.api_dollars:,.2f}."
                    ),
                    action="Keep prompts and file context stable to preserve cache hits.",
                )
            )

    if result.events:
        assumed = result.tier_sources.get("assumed", 0) + result.tier_sources.get(
            "current-config", 0
        )
        if assumed / len(result.events) >= 0.8:
            insights.append(
                Insight(
                    severity="warn",
                    title="Service tier inferred",
                    detail=(
                        f"{assumed:,} of {len(result.events):,} events used an inferred tier "
                        "rather than a logged tier."
                    ),
                    action=(
                        "Pin known usage with --service-tier or --tier-overrides for sharper costs."
                    ),
                )
            )

    projects = aggregate_projects(result, options, rate_card=card)
    if projects and total.costs.adjusted_credits:
        top = projects[0]
        share = top.costs.adjusted_credits / total.costs.adjusted_credits
        if share >= 0.4:
            insights.append(
                Insight(
                    severity="info",
                    title="Spend concentrated in one project",
                    detail=(
                        f"{top.label} accounts for {share:.1%} of credits "
                        f"({top.costs.adjusted_credits:,.2f})."
                    ),
                    action="Run codex-meter project --top 5 to inspect the largest workspaces.",
                )
            )

    daily = aggregate_daily(result, options, rate_card=card)
    if len(daily) >= 3:
        midpoint = len(daily) // 2
        earlier = sum(row.costs.adjusted_credits for row in daily[:midpoint]) / max(midpoint, 1)
        later_count = len(daily) - midpoint
        later = sum(row.costs.adjusted_credits for row in daily[midpoint:]) / max(later_count, 1)
        if earlier and later / earlier >= 2:
            insights.append(
                Insight(
                    severity="warn",
                    title="Daily usage is accelerating",
                    detail=f"Recent daily credits are {later / earlier:.1f}x the earlier average.",
                    action="Run codex-meter forecast --cap <plan-credits> to check depletion risk.",
                )
            )

    return insights


def cache_savings(result: LoadResult, rate_card: RateCard) -> CostTotals:
    savings = CostTotals()
    for event in result.events:
        savings.add(rate_card.cache_savings_for(event.usage, event.model, event.service_tier))
    return savings


def insights_payload(insights: list[Insight]) -> dict:
    return {"insights": [asdict(item) for item in insights]}


def render_insights_markdown(insights: list[Insight]) -> str:
    lines = [
        "| Severity | Insight | Detail | Action |",
        "| --- | --- | --- | --- |",
    ]
    for insight in insights:
        lines.append(
            "| "
            + " | ".join(
                [
                    insight.severity,
                    _escape_markdown(insight.title),
                    _escape_markdown(insight.detail),
                    _escape_markdown(insight.action),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|")
