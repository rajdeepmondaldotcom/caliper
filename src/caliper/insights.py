from __future__ import annotations

from dataclasses import asdict, dataclass

from caliper.aggregation import (
    aggregate_daily,
    aggregate_projects,
    aggregate_total,
    event_cache_savings,
)
from caliper.models import CostTotals, LoadResult, RuntimeOptions
from caliper.pricing import RateCard, load_rate_card


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
    card = rate_card or load_rate_card(options)
    total = aggregate_total(result, options, rate_card=card)
    projects = aggregate_projects(result, options, rate_card=card)
    daily = aggregate_daily(result, options, rate_card=card)
    return build_insights_from(
        result=result,
        rate_card=card,
        total=total,
        projects=projects,
        daily=daily,
    )


def build_insights_from(
    *,
    result: LoadResult,
    rate_card: RateCard,
    total,
    projects,
    daily,
) -> list[Insight]:
    """Build insights from pre-computed aggregates.

    Use this when the caller already has ``aggregate_total``,
    ``aggregate_projects``, and ``aggregate_daily`` outputs at hand —
    e.g. the Textual TUI's reactive AppSnapshot. ``build_insights`` is
    the convenience wrapper that does the aggregation itself.
    """
    candidates = [
        _cache_reuse_insight(result, total, rate_card),
        _service_tier_insight(result),
        _project_concentration_insight(projects, total),
        _daily_acceleration_insight(daily),
    ]
    return [item for item in candidates if item is not None]


def _cache_reuse_insight(result: LoadResult, total, card: RateCard) -> Insight | None:
    if not total.totals.input_tokens or not total.totals.cached_input_tokens:
        return None
    cache_ratio = total.totals.cached_input_tokens / total.totals.input_tokens
    savings = cache_savings(result, card)
    return Insight(
        severity="info",
        title="High cache reuse" if cache_ratio >= 0.5 else "Low cache reuse",
        detail=(
            f"{cache_ratio:.1%} of input tokens were served from cache, "
            f"saving about {savings.adjusted_credits:,.2f} credits and "
            f"${savings.api_dollars:,.2f}."
        ),
        action="Keep prompts and file context stable to preserve cache hits.",
    )


def _service_tier_insight(result: LoadResult) -> Insight | None:
    if not result.events:
        return None
    assumed = result.tier_sources.get("assumed", 0) + result.tier_sources.get("current-config", 0)
    if assumed / len(result.events) < 0.8:
        return None
    return Insight(
        severity="warn",
        title="Service tier inferred",
        detail=(
            f"{assumed:,} of {len(result.events):,} events used an inferred tier "
            "rather than a logged tier."
        ),
        action="Pin known usage with --service-tier or --tier-overrides for sharper costs.",
    )


def _project_concentration_insight(projects: list, total) -> Insight | None:
    if not projects or not total.costs.adjusted_credits:
        return None
    top = projects[0]
    share = float(top.costs.adjusted_credits / total.costs.adjusted_credits)
    if share < 0.4:
        return None
    return Insight(
        severity="info",
        title="Spend concentrated in one project",
        detail=(
            f"{top.label} accounts for {share:.1%} of credits ({top.costs.adjusted_credits:,.2f})."
        ),
        action="Run caliper project --top 5 to inspect the largest workspaces.",
    )


def _daily_acceleration_insight(daily: list) -> Insight | None:
    if len(daily) < 3:
        return None
    earlier, later = _split_daily_average_credits(daily)
    if not earlier or later / earlier < 2:
        return None
    return Insight(
        severity="warn",
        title="Daily usage is accelerating",
        detail=f"Recent daily credits are {later / earlier:.1f}x the earlier average.",
        action="Run caliper forecast --cap <plan-credits> to check depletion risk.",
    )


def _split_daily_average_credits(daily: list) -> tuple:
    midpoint = len(daily) // 2
    earlier = sum(row.costs.adjusted_credits for row in daily[:midpoint]) / max(midpoint, 1)
    later_count = len(daily) - midpoint
    later = sum(row.costs.adjusted_credits for row in daily[midpoint:]) / max(later_count, 1)
    return earlier, later


def cache_savings(result: LoadResult, rate_card: RateCard) -> CostTotals:
    savings = CostTotals()
    for event in result.events:
        savings.add(event_cache_savings(rate_card, event))
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
