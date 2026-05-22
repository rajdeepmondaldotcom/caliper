from __future__ import annotations

from dataclasses import asdict, dataclass, field

from caliper.aggregation import (
    aggregate_daily,
    aggregate_projects,
    aggregate_total,
    event_cache_savings,
)
from caliper.evidence import (
    OVERALL_EVIDENCE_DIMENSION_NAMES,
    evidence_dimensions,
    overall_evidence_grade,
)
from caliper.models import CostTotals, LoadResult, RuntimeOptions, decimal_string
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
    category: str = "usage"
    priority: int = 50
    confidence: str = "medium"
    impact_usd_exact: str = ""
    impact_label: str = ""
    evidence_metrics: dict[str, object] = field(default_factory=dict)
    commands: tuple[str, ...] = ()


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
    items = build_insights_from(
        result=result,
        rate_card=card,
        total=total,
        projects=projects,
        daily=daily,
    )
    try:
        from caliper.inefficiencies import build_inefficiency_findings

        inefficiencies = build_inefficiency_findings(result, options, card)[:3]
    except Exception:
        inefficiencies = []
    items.extend(_inefficiency_insight(item) for item in inefficiencies)
    return sorted(items, key=lambda item: (-item.priority, item.title))


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
        _accuracy_insight(result, total),
        _cache_reuse_insight(result, total, rate_card),
        _service_tier_insight(result),
        _project_concentration_insight(projects, total),
        _daily_acceleration_insight(daily),
        _model_concentration_insight(total),
        _vendor_mix_insight(total),
        _top_waste_insight(result, rate_card),
        _demand_shift_insight(result, rate_card),
    ]
    return sorted(
        [item for item in candidates if item is not None],
        key=lambda item: (-item.priority, item.title),
    )


def _top_waste_insight(result: LoadResult, rate_card: RateCard) -> Insight | None:
    """Surface the single highest-impact :class:`~caliper.efficiency.Finding`
    as a home-screen insight so the dashboard headline reflects what is
    actually fixable in dollar terms."""
    if not result.events:
        return None
    try:
        from caliper.efficiency import run_audit
    except ImportError:
        return None
    try:
        options = _synthetic_options(result)
        findings = run_audit(result, options, rate_card)
    except Exception:
        return None
    if not findings:
        return None
    top = findings[0]
    impact = float(top.impact_usd_exact)
    if impact <= 0:
        return None
    return Insight(
        severity="warn" if top.severity != "info" else "info",
        title=f"${impact:,.2f} of waste is fixable",
        detail=top.detail,
        action=top.payback_action,
        scope=SCOPE_HOME,
        evidence=top.evidence,
        next_command="caliper recommend",
        category="waste",
        priority=95,
        confidence=top.confidence,
        impact_usd_exact=decimal_string(top.impact_usd_exact),
        impact_label=f"${impact:,.2f} fixable",
        evidence_metrics=dict(top.evidence_metrics),
        commands=top.commands or ("caliper audit", "caliper recommend"),
    )


def _demand_shift_insight(result: LoadResult, rate_card: RateCard) -> Insight | None:
    """Fastest-growing model. Used by the Models dashboard to flag
    capacity-planning conversations early."""
    if not result.events:
        return None
    try:
        from caliper.predict import forecast_per_model
    except ImportError:
        return None
    forecasts = forecast_per_model(result.events, rate_card, "UTC")
    growing = [card for card in forecasts if card.growing and card.daily_mean_tokens > 0]
    if not growing:
        return None
    top = max(growing, key=lambda card: card.trend_slope_tokens_per_day)
    if top.trend_slope_tokens_per_day <= 0:
        return None
    return Insight(
        severity="info",
        title=f"{top.model} demand is growing",
        detail=(
            f"{top.model} usage is rising by ~{int(top.trend_slope_tokens_per_day):+,} tokens/day. "
            f"30-day projection: ${top.projected_cost_30d_usd:,.2f}."
        ),
        action="caliper predict --per-model to see the full demand split.",
        scope=SCOPE_MODELS,
        evidence=(
            f"slope {int(top.trend_slope_tokens_per_day):+,} tokens/day",
            f"projected 30d share {top.projected_share_30d:.0%}",
        ),
        next_command="caliper predict",
        category="forecast",
        priority=70,
        confidence="medium",
        impact_label=f"${top.projected_cost_30d_usd:,.2f}/mo at current trend",
        evidence_metrics={
            "model": top.model,
            "model_vendor": top.model_vendor,
            "slope_tokens_per_day": top.trend_slope_tokens_per_day,
            "projected_cost_30d_usd": top.projected_cost_30d_usd,
        },
        commands=("caliper predict", "caliper recommend"),
    )


def _synthetic_options(result: LoadResult):
    """Build a minimal RuntimeOptions for finders that only require the
    window span for monthly extrapolation."""
    import datetime as _dt
    from pathlib import Path as _Path

    from caliper.models import RuntimeOptions as _RuntimeOptions

    if not result.events:
        now = _dt.datetime.now(tz=_dt.UTC)
        start, end = now - _dt.timedelta(days=1), now
    else:
        start = min(event.timestamp for event in result.events)
        end = max(event.timestamp for event in result.events) + _dt.timedelta(seconds=1)
    return _RuntimeOptions(
        session_root=_Path("/dev/null"),
        state_db=_Path("/dev/null"),
        config_path=_Path("/dev/null"),
        start=start,
        end=end,
        timezone="UTC",
        pricing_mode="model",
        service_tier="auto",
        unknown_service_tier="current-config",
        tier_overrides=None,
        rates_file=None,
        dedupe=True,
        parse_cache=True,
        default_model="gpt-5.5",
        show_prompts=False,
        show_paths=False,
        offline=True,
        compact=False,
        width=None,
        top_threads=0,
    )


def _inefficiency_insight(finding) -> Insight:
    return Insight(
        severity="warn" if finding.severity in {"warn", "fail"} else "info",
        title=finding.title,
        detail=f"{finding.detail} Evidence: {finding.evidence_status}.",
        action=finding.action,
        scope=finding.scope,
        evidence=finding.evidence,
        next_command=(finding.commands[0] if finding.commands else "caliper inefficiencies"),
        category="inefficiency",
        priority=88 if finding.confidence == "high" else 78,
        confidence=finding.confidence,
        impact_usd_exact=decimal_string(finding.impact_usd_exact),
        impact_label=f"${finding.impact_usd_exact:,.2f} impact",
        evidence_metrics=finding.evidence_metrics
        | {
            "evidence_status": finding.evidence_status,
            "sample_size": finding.sample_size,
            "baseline": finding.baseline,
        },
        commands=finding.commands or ("caliper inefficiencies",),
    )


def _accuracy_insight(result: LoadResult, total) -> Insight | None:
    """Surface when the numbers should not be treated as invoice-grade."""
    dimensions = evidence_dimensions(result, total)
    grade = overall_evidence_grade(dimensions)
    if grade == "exact":
        return None
    ordered = sorted(
        [
            dimension
            for dimension in dimensions
            if dimension.name in OVERALL_EVIDENCE_DIMENSION_NAMES and dimension.grade != "exact"
        ],
        key=lambda dimension: (dimension.grade, dimension.name),
    )
    reasons = [reason for dimension in ordered for reason in dimension.reasons]
    first = ordered[0] if ordered else None
    scope = SCOPE_DOCTOR if first and first.name in {"usage", "pricing"} else SCOPE_HOME
    detail = _accuracy_detail(grade, total, reasons)
    return Insight(
        severity="warn" if grade in {"estimated", "partial"} else "fail",
        title=f"Accuracy is {grade}",
        detail=detail,
        action="Run `caliper evidence` or `caliper doctor` before using this as a budget fact.",
        scope=scope,
        evidence=tuple(reasons[:3]),
        next_command="caliper evidence",
        category="accuracy",
        priority=100,
        confidence="high",
        evidence_metrics={
            "overall": grade,
            "dimensions": {dimension.name: dimension.grade for dimension in dimensions},
        },
        commands=("caliper evidence", "caliper doctor"),
    )


def _accuracy_detail(grade: str, total, reasons: list[str]) -> str:
    events = total.totals.events
    priced = min(
        events,
        max(events - total.costs.unpriced_events, 0) + total.costs.vendor_reported_events,
    )
    unsupported = max(events - priced, 0)
    if events and unsupported:
        return (
            f"Cost evidence is {grade}: {priced:,}/{events:,} events priced; "
            f"{unsupported:,} unsupported."
        )
    return f"Cost evidence is {grade}. " + (
        reasons[0] if reasons else "Run doctor to see which input is incomplete."
    )


def _model_concentration_insight(total) -> Insight | None:
    """Surface the single model that owns the most spend."""
    breakdowns = getattr(total, "model_breakdowns", None) or {}
    if not breakdowns or not total.costs.cost_usd:
        return None
    top = max(breakdowns.values(), key=lambda mb: float(mb.costs.cost_usd))
    share = float(top.costs.cost_usd) / float(total.costs.cost_usd or 1)
    if share < 0.5:
        return None
    return Insight(
        severity="info",
        title=f"{top.model} is {share:.0%} of selected-window cost",
        detail=(
            f"{top.model} accounts for {share:.0%} of selected-window cost. "
            "Run advisor with the active rate card before changing routing."
        ),
        action="caliper advise --strict",
        scope=SCOPE_HOME,
        evidence=(f"{share:.0%} on {top.model}",),
        next_command="caliper advise --strict",
        category="optimization",
        priority=80,
        confidence="medium",
        impact_usd_exact=decimal_string(top.costs.cost_usd),
        impact_label=f"${top.costs.cost_usd:,.2f} controlled by one model",
        evidence_metrics={
            "cost_share": share,
            "model": top.model,
            "events": top.totals.events,
        },
        commands=("caliper models", "caliper advise --strict"),
    )


def _vendor_mix_insight(total) -> Insight | None:
    """Surface the model-vendor mix when more than one vendor is present."""
    breakdowns = getattr(total, "model_breakdowns", None) or {}
    if not breakdowns:
        return None
    by_vendor: dict[str, float] = {}
    for mb in breakdowns.values():
        vendor = getattr(mb, "model_vendor", "unknown") or "unknown"
        by_vendor[vendor] = by_vendor.get(vendor, 0.0) + float(mb.costs.cost_usd)
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
        category="procurement",
        priority=45,
        confidence="medium",
        evidence_metrics={"vendor_cost_share": by_vendor},
        commands=("caliper models --per-model", "caliper models --by vendor"),
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
            f"{cache_ratio:.1%} of input tokens were recorded as cached input. "
            f"Estimated cache savings: ${savings.cost_usd:,.2f}."
        ),
        action="Stable prompts keep that working.",
        scope=SCOPE_HOME,
        evidence=(f"{cache_ratio:.1%} cached-input share",),
        category="cache",
        priority=70 if cache_ratio < 0.5 else 55,
        confidence="high",
        impact_usd_exact=decimal_string(savings.cost_usd),
        impact_label=f"est. ${savings.cost_usd:,.2f} cache savings",
        evidence_metrics={
            "cache_hit_ratio": cache_ratio,
            "input_tokens": total.totals.input_tokens,
            "cached_input_tokens": total.totals.cached_input_tokens,
        },
        commands=("caliper models --per-model",),
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
        category="accuracy",
        priority=90,
        confidence="high",
        evidence=(f"{assumed:,}/{len(result.events):,} events inferred",),
        evidence_metrics={
            "inferred_events": assumed,
            "events": len(result.events),
            "inferred_ratio": assumed / len(result.events),
        },
        commands=("caliper --service-tier standard", "caliper doctor"),
    )


def _project_concentration_insight(projects: list, total) -> Insight | None:
    if not projects or not total.costs.cost_usd:
        return None
    top = projects[0]
    share = float(top.costs.cost_usd / total.costs.cost_usd)
    if share < 0.4:
        return None
    label = _safe_project_label(top.label)
    return Insight(
        severity="info",
        title=f"{label} is {share:.0%} of selected-window cost",
        detail=(
            f"{label} accounts for ${top.costs.cost_usd:,.2f} in the selected window. "
            "Decide whether that concentration is expected."
        ),
        action="caliper project --top 5 to inspect the rest.",
        scope=SCOPE_PROJECTS,
        next_command="caliper project --top 5",
        category="attribution",
        priority=75,
        confidence="high",
        impact_usd_exact=decimal_string(top.costs.cost_usd),
        impact_label=f"${top.costs.cost_usd:,.2f} in {label}",
        evidence=(f"{share:.0%} cost share", f"{top.totals.events:,} events"),
        evidence_metrics={
            "project": label,
            "cost_share": share,
            "events": top.totals.events,
        },
        commands=("caliper project --top 5", f"caliper project --project {label}"),
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
    earlier, later = _split_daily_average_cost_usd(daily)
    if not earlier or later / earlier < 2:
        return None
    return Insight(
        severity="warn",
        title="Daily usage is accelerating",
        detail=(
            f"Recent daily cost averages ${later:,.2f}. The earlier average was "
            f"${earlier:,.2f}. The trend is up, not noisy."
        ),
        action="caliper forecast --cap <monthly-usd-cap> to test depletion risk.",
        scope=SCOPE_DAILY,
        next_command="caliper forecast",
        category="forecast",
        priority=85,
        confidence="medium",
        impact_label=f"daily average moved from ${earlier:,.2f} to ${later:,.2f}",
        evidence=(
            f"earlier average ${earlier:,.2f}",
            f"recent average ${later:,.2f}",
        ),
        evidence_metrics={
            "earlier_daily_average": float(earlier),
            "recent_daily_average": float(later),
        },
        commands=("caliper forecast", "caliper compare"),
    )


def _split_daily_average_cost_usd(daily: list) -> tuple:
    midpoint = len(daily) // 2
    earlier = sum(row.costs.cost_usd for row in daily[:midpoint]) / max(midpoint, 1)
    later_count = len(daily) - midpoint
    later = sum(row.costs.cost_usd for row in daily[midpoint:]) / max(later_count, 1)
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
