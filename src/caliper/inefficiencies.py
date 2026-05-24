"""Trust-first inefficiency orchestration.

This module composes deterministic finders from ``efficiency.py`` with the
new attribution-based signals. It deliberately suppresses weak signals rather
than manufacturing a recommendation from thin data.
"""

from __future__ import annotations

import calendar
import datetime as dt
import statistics
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from caliper.aggregation import aggregate_daily, event_cost
from caliper.analysis.session_shape import DIAGNOSTIC_TOOLS, EXECUTION_TOOLS
from caliper.attribution import (
    agent_summary,
    attribution_findings,
    build_agent_attributions,
    build_skill_attributions,
    skill_summary,
)
from caliper.budgets import (
    SEVERITY_OK,
    current_period_intervals,
    evaluate,
    parse_budgets_table,
    usage_for_periods,
)
from caliper.efficiency import run_audit
from caliper.humanize import session_label_lookup
from caliper.models import Finding, LoadResult, RuntimeOptions, UsageEvent, decimal_string
from caliper.pricing import RateCard

MIN_ACTIVE_DAYS_FOR_BUDGET_FORECAST = 3
MIN_COMMIT_BASELINE = 5
MIN_REWORK_BASELINE = 5
MIN_IMPACT = Decimal("0.10")


def build_inefficiency_findings(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    *,
    budget_config: dict[str, Any] | None = None,
    audit_findings: list[Finding] | None = None,
    agents: list[Any] | None = None,
    skills: list[Any] | None = None,
) -> list[Finding]:
    """Return ranked, evidence-labelled inefficiency findings.

    Findings are omitted when their sample is too small, their impact cannot
    be quantified, or their evidence would be unsupported.
    """
    findings: list[Finding] = []
    findings.extend(
        audit_findings if audit_findings is not None else run_audit(result, options, rate_card)
    )

    agents = agents if agents is not None else build_agent_attributions(result, rate_card)
    skills = skills if skills is not None else build_skill_attributions(result, rate_card)
    findings.extend(attribution_findings(agents, skills, options))
    findings.extend(_rework_loop_findings(result, options, rate_card))
    findings.extend(_commit_efficiency_findings(result, options, rate_card))
    findings.extend(_budget_depletion_findings(result, options, rate_card, budget_config))

    return sorted(
        [finding for finding in findings if finding.impact_usd_exact >= MIN_IMPACT],
        key=lambda finding: (
            -finding.impact_usd_exact,
            _confidence_rank(finding.confidence),
            finding.code,
        ),
    )


def inefficiency_payload(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    *,
    budget_config: dict[str, Any] | None = None,
) -> dict[str, object]:
    agents = build_agent_attributions(result, rate_card)
    skills = build_skill_attributions(result, rate_card)
    findings = build_inefficiency_findings(
        result,
        options,
        rate_card,
        budget_config=budget_config,
    )
    return {
        "findings": [finding_to_record(item) for item in findings],
        "finding_count": len(findings),
        "estimated_avoidable_cost_usd_exact": decimal_string(_largest_impact(findings)),
        "largest_single_finding_impact_usd_exact": decimal_string(_largest_impact(findings)),
        "sum_of_finding_impacts_usd_exact": decimal_string(_sum_impacts(findings)),
        "monthly_projected_savings_usd_exact": decimal_string(_largest_monthly_impact(findings)),
        "sum_of_monthly_projected_savings_usd_exact": decimal_string(
            sum((item.monthly_projected_savings_usd for item in findings), Decimal("0"))
        ),
        "rollup_method": "largest_single_finding_to_avoid_overlapping_sums",
        "agent_summary": agent_summary(agents),
        "skill_summary": skill_summary(skills, result),
    }


def finding_to_record(finding: Finding) -> dict[str, object]:
    return {
        "code": finding.code,
        "severity": finding.severity,
        "title": finding.title,
        "detail": finding.detail,
        "action": finding.action,
        "payback_action": finding.payback_action,
        "scope": finding.scope,
        "impact_usd": float(finding.impact_usd_exact),
        "impact_usd_exact": decimal_string(finding.impact_usd_exact),
        "monthly_projected_savings_usd": float(finding.monthly_projected_savings_usd),
        "monthly_projected_savings_usd_exact": decimal_string(
            finding.monthly_projected_savings_usd
        ),
        "confidence": finding.confidence,
        "evidence_status": finding.evidence_status,
        "sample_size": finding.sample_size,
        "baseline": finding.baseline,
        "evidence": list(finding.evidence),
        "evidence_metrics": finding.evidence_metrics,
        "commands": list(finding.commands),
    }


def _rework_loop_findings(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
) -> list[Finding]:
    by_session: dict[str, list[UsageEvent]] = defaultdict(list)
    for event in result.events:
        if event.session_id:
            by_session[event.session_id].append(event)
    if len(by_session) < MIN_REWORK_BASELINE:
        return []

    costs: dict[str, Decimal] = {}
    tool_counts: dict[str, Counter[str]] = {}
    for session_id, events in by_session.items():
        cost = Decimal("0")
        counts: Counter[str] = Counter()
        for event in events:
            event_total, _, _ = event_cost(rate_card, event)
            cost += event_total.cost_usd
            if event.turn_facts:
                counts.update(event.turn_facts.tool_names)
        costs[session_id] = cost
        tool_counts[session_id] = counts

    positive_costs = [float(cost) for cost in costs.values() if cost > 0]
    if len(positive_costs) < MIN_REWORK_BASELINE:
        return []
    median = statistics.median(positive_costs)
    labels = session_label_lookup(result.events, options.timezone)
    findings: list[Finding] = []
    for session_id, counts in tool_counts.items():
        diagnostic = sum(count for name, count in counts.items() if name in DIAGNOSTIC_TOOLS)
        execution = sum(count for name, count in counts.items() if name in EXECUTION_TOOLS)
        total_tools = sum(counts.values())
        if diagnostic < 3 or execution < 3 or total_tools < 20:
            continue
        excess = costs[session_id] - Decimal(str(median))
        if excess < MIN_IMPACT:
            continue
        findings.append(
            Finding(
                code="REWORK_LOOP",
                severity="warn",
                title="Debug/edit loop cost outlier",
                detail=(
                    f"{labels.get(session_id, session_id)} mixed {diagnostic:,} diagnostic and "
                    f"{execution:,} edit tools across {total_tools:,} tool calls."
                ),
                action="Inspect the session before repeating the same debug loop.",
                payback_action="Break the loop with a smaller repro or a human checkpoint.",
                scope="sessions",
                impact_usd_exact=excess,
                monthly_projected_savings_usd=_scale_to_monthly(excess, options),
                confidence="medium",
                evidence=(labels.get(session_id, session_id), f"{total_tools:,} tool calls"),
                evidence_metrics={
                    "session_id": session_id,
                    "session_label": labels.get(session_id, session_id),
                    "diagnostic_tool_calls": diagnostic,
                    "execution_tool_calls": execution,
                    "total_tool_calls": total_tools,
                    "baseline_median_cost_usd": median,
                },
                commands=("caliper session",),
                event_ids=(session_id,),
                evidence_status="estimated",
                sample_size=len(by_session),
                baseline=f"session median ${median:,.2f}",
            )
        )
    return findings


def _commit_efficiency_findings(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
) -> list[Finding]:
    by_commit: dict[str, Decimal] = defaultdict(Decimal)
    for event in result.events:
        sha = event.thread.git_sha
        if not sha:
            continue
        cost, _, _ = event_cost(rate_card, event)
        by_commit[sha] += cost.cost_usd
    if len(by_commit) < MIN_COMMIT_BASELINE:
        return []
    costs = [float(value) for value in by_commit.values() if value > 0]
    if len(costs) < MIN_COMMIT_BASELINE:
        return []
    median = statistics.median(costs)
    findings: list[Finding] = []
    for sha, cost in by_commit.items():
        if float(cost) < median * 3:
            continue
        excess = cost - Decimal(str(median))
        if excess < MIN_IMPACT:
            continue
        short = sha[:12]
        findings.append(
            Finding(
                code="COMMIT_COST_OUTLIER",
                severity="info",
                title="Commit cost is above repo baseline",
                detail=f"Commit {short} cost ${cost:,.2f}; commit median is ${median:,.2f}.",
                action=(
                    "Review commit receipt and identify whether review, debugging, "
                    "or generation drove spend."
                ),
                payback_action=f"Inspect commit {short}.",
                scope="commit",
                impact_usd_exact=excess,
                monthly_projected_savings_usd=_scale_to_monthly(excess, options),
                confidence="medium",
                evidence=(short,),
                evidence_metrics={
                    "git_sha_prefix": short,
                    "observed_cost_usd_exact": decimal_string(cost),
                    "baseline_median_cost_usd": median,
                    "sample_size": len(by_commit),
                },
                commands=(f"caliper commit {short}",),
                event_ids=(sha,),
                evidence_status="partial",
                sample_size=len(by_commit),
                baseline=f"commit median ${median:,.2f}",
            )
        )
    return findings


def _budget_depletion_findings(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    budget_config: dict[str, Any] | None,
) -> list[Finding]:
    raw = (budget_config or {}).get("budgets") or {}
    try:
        budgets = parse_budgets_table(raw if isinstance(raw, dict) else {})
    except ValueError:
        return []
    cost_budgets = [budget for budget in budgets if budget.metric == "cost_usd"]
    if not cost_budgets:
        return []

    now = min(options.end, dt.datetime.now(tz=dt.UTC))
    windows = current_period_intervals(now)
    usage = usage_for_periods(result.events, options, rate_card, now, windows=windows)
    alerts = evaluate(cost_budgets, usage)
    daily = aggregate_daily(result, options, rate_card=rate_card)
    active_days = sum(1 for row in daily if row.totals.events > 0)
    if active_days < MIN_ACTIVE_DAYS_FOR_BUDGET_FORECAST:
        return []

    findings: list[Finding] = []
    for alert in alerts:
        if alert.severity == SEVERITY_OK and alert.used_percent < alert.budget.warn_at * 100:
            continue
        projected = _project_period_usage(alert.budget.period, alert.used, now)
        overage = Decimal(str(max(0.0, projected - alert.budget.limit)))
        if overage < MIN_IMPACT:
            continue
        severity = "fail" if alert.used_percent >= 100 else "warn"
        findings.append(
            Finding(
                code="BUDGET_DEPLETION_DRIVER",
                severity=severity,
                title=f"{alert.budget.period.title()} budget is projected to deplete",
                detail=(
                    f"Current use is ${alert.used:,.2f} against a ${alert.budget.limit:,.2f} "
                    f"{alert.budget.period} budget; projected period use is ${projected:,.2f}."
                ),
                action="Inspect project, model, agent, and skill drivers before the period closes.",
                payback_action="Reduce the highest projected driver.",
                scope="budgets",
                impact_usd_exact=overage,
                monthly_projected_savings_usd=overage,
                confidence="medium",
                evidence=(
                    f"{alert.used_percent:.1f}% used",
                    f"{active_days:,} active days",
                ),
                evidence_metrics={
                    "period": alert.budget.period,
                    "used": alert.used,
                    "limit": alert.budget.limit,
                    "projected": projected,
                    "active_days": active_days,
                },
                commands=("caliper budgets check", "caliper project --top 5"),
                event_ids=(alert.budget.key(),),
                evidence_status="estimated",
                sample_size=active_days,
                baseline=f"{alert.budget.period} budget ${alert.budget.limit:,.2f}",
            )
        )
    return findings


def _project_period_usage(period: str, used: float, now: dt.datetime) -> float:
    elapsed, total = _period_elapsed_total(period, now)
    if elapsed <= 0:
        return used
    return used / elapsed * total


def _largest_impact(findings: list[Finding]) -> Decimal:
    return max((item.impact_usd_exact for item in findings), default=Decimal("0"))


def _largest_monthly_impact(findings: list[Finding]) -> Decimal:
    return max(
        (item.monthly_projected_savings_usd for item in findings),
        default=Decimal("0"),
    )


def _sum_impacts(findings: list[Finding]) -> Decimal:
    return sum((item.impact_usd_exact for item in findings), Decimal("0"))


def _period_elapsed_total(period: str, now: dt.datetime) -> tuple[float, float]:
    local_now = now
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "daily":
        elapsed = max((local_now - day_start).total_seconds() / 86_400.0, 1 / 24)
        return elapsed, 1.0
    if period == "weekly":
        week_start = day_start - dt.timedelta(days=day_start.weekday())
        elapsed = max((local_now - week_start).total_seconds() / 86_400.0, 1.0)
        return elapsed, 7.0
    if period == "monthly":
        month_start = day_start.replace(day=1)
        elapsed = max((local_now - month_start).total_seconds() / 86_400.0, 1.0)
        _, days_in_month = calendar.monthrange(local_now.year, local_now.month)
        return elapsed, float(days_in_month)
    return 1.0, 1.0


def _scale_to_monthly(impact: Decimal, options: RuntimeOptions) -> Decimal:
    window_days = max((options.end - options.start).total_seconds() / 86_400.0, 1.0)
    return Decimal(str(round(float(impact) * (30.0 / window_days), 4)))


def _confidence_rank(confidence: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(confidence, 9)


__all__ = [
    "build_inefficiency_findings",
    "finding_to_record",
    "inefficiency_payload",
]
