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
    scope: str = "home"
    evidence: tuple[str, ...] = ()
    next_command: str = ""


# Canonical scope labels. Every insight names which screen it speaks to.
SCOPE_HOME = "home"
SCOPE_DAILY = "daily"
SCOPE_SESSIONS = "sessions"
SCOPE_PROJECTS = "projects"
SCOPE_MODELS = "models"
SCOPE_LIMITS = "limits"
SCOPE_FORECAST = "forecast"
SCOPE_BUDGETS = "budgets"
SCOPE_DOCTOR = "doctor"
SCOPE_RECEIPT = "receipt"

KNOWN_INSIGHT_SCOPES: tuple[str, ...] = (
    SCOPE_HOME,
    SCOPE_DAILY,
    SCOPE_SESSIONS,
    SCOPE_PROJECTS,
    SCOPE_MODELS,
    SCOPE_LIMITS,
    SCOPE_FORECAST,
    SCOPE_BUDGETS,
    SCOPE_DOCTOR,
    SCOPE_RECEIPT,
)


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
        _model_concentration_insight(total),
        _vendor_mix_insight(total),
    ]
    return [item for item in candidates if item is not None]


def _model_concentration_insight(total) -> Insight | None:
    """Surface the single model that owns the most spend."""
    breakdowns = getattr(total, "model_breakdowns", None) or {}
    if not breakdowns or not total.costs.adjusted_credits:
        return None
    top = max(breakdowns.values(), key=lambda mb: float(mb.costs.adjusted_credits))
    share = float(top.costs.adjusted_credits) / float(total.costs.adjusted_credits or 1)
    if share < 0.5:
        return None
    return Insight(
        severity="info",
        title=f"{top.model} is {share:.0%} of credits",
        detail=(
            f"You don't have a cost problem. You have a {top.model} problem. "
            "Try a cheaper sibling and re-run whatif to compare."
        ),
        action=f"caliper whatif --hypothetical-model <cheaper> against {top.model}",
        scope=SCOPE_HOME,
        evidence=(f"{share:.0%} on {top.model}",),
        next_command="caliper whatif --hypothetical-model claude-sonnet-4.6",
    )


def _vendor_mix_insight(total) -> Insight | None:
    """Surface the model-vendor mix when more than one vendor is present."""
    breakdowns = getattr(total, "model_breakdowns", None) or {}
    if not breakdowns:
        return None
    by_vendor: dict[str, float] = {}
    for mb in breakdowns.values():
        vendor = getattr(mb, "model_vendor", "unknown") or "unknown"
        by_vendor[vendor] = by_vendor.get(vendor, 0.0) + float(mb.costs.api_dollars)
    if len(by_vendor) < 2:
        return None
    total_dollars = sum(by_vendor.values()) or 1.0
    parts = [
        f"{vendor.title()} {dollars / total_dollars:.0%}"
        for vendor, dollars in sorted(by_vendor.items(), key=lambda kv: -kv[1])
    ]
    return Insight(
        severity="info",
        title="Spend splits across vendors",
        detail=(
            "Vendor mix: " + ", ".join(parts) + ". "
            "If you hold an enterprise contract on one side, that is the lever."
        ),
        action="caliper models --per-model to drill down.",
        scope=SCOPE_MODELS,
        evidence=tuple(parts),
        next_command="caliper models --per-model",
    )


def _cache_reuse_insight(result: LoadResult, total, card: RateCard) -> Insight | None:
    if not total.totals.input_tokens or not total.totals.cached_input_tokens:
        return None
    cache_ratio = total.totals.cached_input_tokens / total.totals.input_tokens
    savings = cache_savings(result, card)
    return Insight(
        severity="info",
        title="High cache reuse" if cache_ratio >= 0.5 else "Low cache reuse",
        detail=(
            f"{cache_ratio:.1%} of input tokens came from cache. "
            f"That saved {savings.adjusted_credits:,.0f} credits and "
            f"${savings.api_dollars:,.2f}."
        ),
        action="Stable prompts keep that working.",
        scope=SCOPE_HOME,
        evidence=(f"{cache_ratio:.1%} cache hit",),
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
            "instead of a logged one. Pin it to sharpen the number."
        ),
        action="caliper --service-tier <name> to pin.",
        scope=SCOPE_MODELS,
        next_command="caliper --service-tier standard",
    )


def _project_concentration_insight(projects: list, total) -> Insight | None:
    if not projects or not total.costs.adjusted_credits:
        return None
    top = projects[0]
    share = float(top.costs.adjusted_credits / total.costs.adjusted_credits)
    if share < 0.4:
        return None
    label = _safe_project_label(top.label)
    return Insight(
        severity="info",
        title=f"{label} is {share:.0%} of credits",
        detail=(
            f"{label} ran up {top.costs.adjusted_credits:,.0f} credits. "
            "The next projects together are less. Decide if that is the intent."
        ),
        action="caliper project --top 5 to inspect the rest.",
        scope=SCOPE_PROJECTS,
        next_command="caliper project --top 5",
    )


def _safe_project_label(label: str) -> str:
    """Trim a project label to a basename so insights do not leak full paths."""
    if not label:
        return ""
    if label.startswith(("/", "~")):
        from pathlib import Path

        name = Path(label).name
        return name or label
    return label


def _daily_acceleration_insight(daily: list) -> Insight | None:
    if len(daily) < 3:
        return None
    earlier, later = _split_daily_average_credits(daily)
    if not earlier or later / earlier < 2:
        return None
    return Insight(
        severity="warn",
        title="Daily usage is accelerating",
        detail=(
            f"Recent daily credits average {later:,.0f}. The earlier average was "
            f"{earlier:,.0f}. The trend is up, not noisy."
        ),
        action="caliper forecast --cap <plan-credits> to test depletion risk.",
        scope=SCOPE_DAILY,
        next_command="caliper forecast",
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
