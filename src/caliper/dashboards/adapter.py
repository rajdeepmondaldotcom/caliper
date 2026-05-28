"""Adapter — map Caliper aggregator output to the handoff Dashboard shape.

The renderer (`caliper.dashboards.html`) consumes a `Dashboard` dataclass
defined in `data_models.py`. This adapter is the single bridge between our
existing `LoadResult` + `RuntimeOptions` + the existing aggregators /
insights / forecasts / evidence helpers and that contract.

Public entrypoint:

    build_handoff_dashboard(result, options, *, with_deltas=True, ...) -> Dashboard

Everything below is internal and named `_build_*` for grep-ability.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Any

from caliper.aggregation import (
    aggregate_daily,
    aggregate_model_mode,
    aggregate_overview_windows,
    aggregate_projects,
    aggregate_sessions,
    aggregate_total,
    event_cost,
)
from caliper.analysis.session_shape import (
    CATEGORY_DIAGNOSTIC,
    CATEGORY_EXECUTION,
    CATEGORY_EXPLORATION,
    CATEGORY_MIXED,
    CATEGORY_NONE,
    DIAGNOSTIC_TOOLS,
    EXECUTION_TOOLS,
    EXPLORATION_TOOLS,
    SessionShapeReport,
    compute_session_shape,
)
from caliper.anomaly import detect_actionable_anomalies
from caliper.attribution import build_agent_attributions, build_skill_attributions
from caliper.budgets import (
    SEVERITY_BREACH,
    SEVERITY_WARN,
    current_period_intervals,
    max_severity,
    parse_budgets_table,
    usage_for_periods,
)
from caliper.budgets import (
    evaluate as evaluate_budgets,
)
from caliper.dashboards.data_models import (
    DASHBOARD_SCHEMA_VERSION,
    AdvisorRecommendation,
    AgentRow,
    AnomalyRow,
    Banner,
    BriefFinding,
    BudgetRow,
    CacheLeverageRow,
    CaliperMeta,
    CohortDeltaRow,
    ComparisonSignal,
    DailyPoint,
    Dashboard,
    DecisionQueueItem,
    EvidenceRow,
    ExecutiveBrief,
    ImpactCard,
    InefficiencyRow,
    Insight,
    LongContextHistogram,
    ModelRow,
    OutputSummary,
    ProjectRow,
    QualityScore,
    QualitySignal,
    RateLimitForecastBand,
    RateLimitPressure,
    SessionRow,
    SkillRow,
    TierProvenance,
    ToolCount,
    Totals,
    UsageWindow,
    WindowMeta,
)
from caliper.efficiency import rank_recommendations, run_audit
from caliper.evidence import evidence_dimensions
from caliper.health import rate_card_age_days
from caliper.humanize import human_datetime as _format_human_datetime
from caliper.humanize import session_label_lookup
from caliper.inefficiencies import build_inefficiency_findings
from caliper.insights import _inefficiency_insight, build_insights_from
from caliper.models import UNKNOWN_PROJECT, Aggregate, LoadResult, RuntimeOptions
from caliper.parser import load_usage
from caliper.predict import (
    forecast_project_burn,
    forecast_rate_limits,
)
from caliper.pricing import MODELS_BY_NAME, RateCard, load_rate_card, model_vendor, normalize_model
from caliper.subscriptions import subscription_cost_caveat

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DASHBOARD_BUILD_STEPS = 14

# Map our `caliper.analysis.session_shape` category constant
# ("exploration"/"execution"/"diagnostic"/"mixed"/"no-tools") to the
# handoff's SessionShapeName literal. Same values today; keeping the map
# explicit makes the renaming a one-line change if either side moves.
_SHAPE_NAME_MAP = {
    CATEGORY_EXPLORATION: "exploration",
    CATEGORY_EXECUTION: "execution",
    CATEGORY_DIAGNOSTIC: "diagnostic",
    CATEGORY_MIXED: "mixed",
    CATEGORY_NONE: "no-tools",
}


def _advance_build(progress: Any | None, detail: str) -> None:
    callback = getattr(progress, "stage_advance", None)
    if callback is not None:
        callback(detail=detail)


# Severity mapping: our internal insights use "info" / "warn" / "fail";
# the handoff design speaks "info" / "warn" / "critical".
_SEVERITY_MAP = {
    "info": "info",
    "warn": "warn",
    "warning": "warn",
    "fail": "critical",
    "critical": "critical",
}

# The vendors Caliper knows how to parse today: Codex, Claude Code, Cursor,
# Aider. Surfaced as the "X of N vendors" count in the page header and the
# banner copy. Bump together when adding a new vendor.
KNOWN_VENDOR_COUNT = 4
ROLLING_USAGE_DAYS = (7, 30, 90)


def tool_category(name: str) -> str:
    """Map a tool name to its handoff category literal."""
    if name in EXPLORATION_TOOLS:
        return "explore"
    if name in EXECUTION_TOOLS:
        return "execute"
    if name in DIAGNOSTIC_TOOLS:
        return "diagnose"
    return "mixed"


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def build_handoff_dashboard(
    result: LoadResult,
    options: RuntimeOptions,
    *,
    with_deltas: bool = True,
    generated_at: dt.datetime | None = None,
    rolling_result: LoadResult | None = None,
    rolling_options: RuntimeOptions | None = None,
    budget_config: dict[str, Any] | None = None,
    progress: Any | None = None,
) -> Dashboard:
    """Assemble the handoff `Dashboard` payload for `render_dashboard`."""
    from caliper import __version__

    rate_card = load_rate_card(options)
    rolling_source = rolling_result or result
    rolling_runtime = rolling_options or options
    total = aggregate_total(result, options, rate_card=rate_card)
    daily_aggregates = aggregate_daily(result, options, rate_card=rate_card)
    shape_report = compute_session_shape(result)
    _advance_build(progress, "totals")

    daily_session_count = _daily_session_counts(result, options)
    daily_points = _build_daily(daily_aggregates, shape_report, options)
    daily_cache_rate = _daily_cache_sparkline(result, options, daily_points)
    deltas = (
        _compute_period_deltas(options, total, shape_report)
        if with_deltas
        else (None, None, None, None)
    )

    totals = _build_totals(
        total=total,
        shape_report=shape_report,
        daily_points=daily_points,
        daily_session_count=daily_session_count,
        daily_cache_rate=daily_cache_rate,
        deltas=deltas,
    )

    _advance_build(progress, "daily shape")
    model_daily_cost = _daily_cost_sparkline_by_key(
        result,
        options,
        rate_card,
        lambda event: (event.model or "unknown", event.model or "unknown"),
    )
    by_model = _build_model_rows(
        aggregate_model_mode(result, options, rate_card=rate_card),
        daily_by_model=model_daily_cost,
    )
    _advance_build(progress, "models")
    project_daily_cost = _daily_cost_sparkline_by_key(
        result,
        options,
        rate_card,
        lambda event: (event.thread.cwd or UNKNOWN_PROJECT, event.thread.cwd or UNKNOWN_PROJECT),
    )
    project_aggregates = aggregate_projects(result, options, rate_card=rate_card)
    project_forecast_bands = _build_project_forecast_bands(
        project_aggregates,
        options,
        project_daily_cost,
    )
    by_project = _build_project_rows(
        project_aggregates,
        result,
        show_paths=options.show_paths,
        options=options,
        daily_by_project=project_daily_cost,
        forecast_bands=project_forecast_bands,
    )
    _advance_build(progress, "projects")
    anomalies = _build_anomaly_rows(
        result=result,
        options=options,
        rate_card=rate_card,
        daily_aggregates=daily_aggregates,
    )
    evidence = _build_evidence(result, total)
    banner = _build_banner(result, options)
    _advance_build(progress, "signals")
    audit_findings = run_audit(result, options, rate_card) if result.events else []
    agent_attributions = build_agent_attributions(result, rate_card)
    skill_attributions = build_skill_attributions(result, rate_card)
    inefficiency_findings = build_inefficiency_findings(
        result,
        options,
        rate_card,
        budget_config=budget_config,
        audit_findings=audit_findings,
        agents=agent_attributions,
        skills=skill_attributions,
    )
    insights = _build_insights(
        result,
        rate_card,
        total=total,
        projects=project_aggregates,
        daily=daily_aggregates,
        audit_findings=audit_findings,
        inefficiency_findings=inefficiency_findings,
    )
    _advance_build(progress, "insights")
    usage_windows = _build_usage_windows(rolling_source, rolling_runtime, rate_card)
    _advance_build(progress, "rolling windows")
    impact_cards = _build_impact_cards(
        result=result,
        rolling_result=rolling_source,
        options=options,
        rolling_options=rolling_runtime,
        total=total,
        by_model=by_model,
        by_project=by_project,
        rate_card=rate_card,
        budget_config=budget_config,
    )
    advisor_recommendations = _build_advisor_recommendations(
        result,
        rate_card,
        options,
        audit_findings=audit_findings,
    )
    _advance_build(progress, "recommendations")
    session_aggregates = aggregate_sessions(result, options, rate_card=rate_card)
    top_sessions = _build_top_sessions(
        result,
        options,
        rate_card,
        session_aggregates=session_aggregates,
    )
    _advance_build(progress, "usage mix")
    agent_rows = _build_agent_rows(
        result,
        rate_card,
        options=options,
        attributions=agent_attributions,
    )
    skill_rows = _build_skill_rows(result, rate_card, attributions=skill_attributions)
    inefficiency_rows = _build_inefficiency_rows(
        result,
        options,
        rate_card,
        budget_config=budget_config,
        findings=inefficiency_findings,
    )
    _advance_build(progress, "attribution")
    rate_limit_pressure = _build_rate_limit_pressure(result)
    rate_limit_pressures = _build_rate_limit_pressures_by_source(result)
    quality_score = _build_quality_score(result, total, evidence)
    comparisons = _build_comparisons(
        totals=totals,
        usage_windows=usage_windows,
        by_project=by_project,
        by_model=by_model,
        top_sessions=top_sessions,
        rate_limit_pressure=rate_limit_pressure,
        quality_score=quality_score,
    )
    decision_queue = _build_decision_queue(
        total=total,
        impact_cards=impact_cards,
        advisor_recommendations=advisor_recommendations,
        inefficiencies=inefficiency_rows,
        anomalies=anomalies,
        top_sessions=top_sessions,
        by_project=by_project,
        by_model=by_model,
        rate_limit_pressure=rate_limit_pressure,
        quality_score=quality_score,
        comparisons=comparisons,
    )
    _advance_build(progress, "decisions")
    executive_brief = _build_executive_brief(
        totals=totals,
        usage_windows=usage_windows,
        decision_queue=decision_queue,
        comparisons=comparisons,
    )
    tier_provenance = _build_tier_provenance(result)
    cache_leverage = _build_cache_leverage(
        result,
        options,
        rate_card,
        session_aggregates=session_aggregates,
    )
    long_context_histogram = _build_long_context_histogram(result, rate_card)
    cohort_deltas = _build_cohort_deltas(result, options, rate_card, total) if with_deltas else []
    budgets = _build_budget_rows(result, options, rate_card, budget_config)
    output_summary = _build_output_summary(result, rate_card, shape_report)
    _advance_build(progress, "forecasts")

    # v2 design: the verdict strip shows up to 4 findings sorted by tone, so
    # cap here. The renderer also slices defensively, but enforcing it in the
    # adapter keeps the data payload aligned with what ships.
    if executive_brief is not None and executive_brief.findings:
        executive_brief = _cap_brief_findings(executive_brief, limit=4)

    window = _build_window(options, result)

    return Dashboard(
        caliper=CaliperMeta(version=__version__, schema_version=DASHBOARD_SCHEMA_VERSION),
        window=window,
        generated_at=(generated_at or dt.datetime.now(tz=dt.UTC)).isoformat(timespec="seconds"),
        totals=totals,
        daily=daily_points,
        by_model=by_model,
        by_project=by_project,
        anomalies=anomalies,
        insights=insights,
        evidence=evidence,
        output_summary=output_summary,
        advisor_recommendations=advisor_recommendations,
        top_sessions=top_sessions,
        agents=agent_rows,
        skills=skill_rows,
        inefficiencies=inefficiency_rows,
        rate_limit_pressure=rate_limit_pressure,
        rate_limit_pressures=rate_limit_pressures,
        quality_score=quality_score,
        executive_brief=executive_brief,
        banner=banner,
        show_paths=options.show_paths,
        tier_provenance=tier_provenance,
        cost_note=subscription_cost_caveat(result.plan_types) or "",
        cache_leverage=cache_leverage,
        long_context_histogram=long_context_histogram,
        cohort_deltas=cohort_deltas,
        budgets=budgets,
    )


# ---------------------------------------------------------------------------
# v2 dashboard: budget burn rows + executive-brief finding cap
# ---------------------------------------------------------------------------


_BRIEF_TONE_RANK = {"critical": 0, "warn": 1, "good": 2, "neutral": 3}


def _cap_brief_findings(brief: ExecutiveBrief, *, limit: int) -> ExecutiveBrief:
    """Sort findings by tone severity, then keep the top ``limit``."""
    findings = sorted(brief.findings, key=lambda f: _BRIEF_TONE_RANK.get(f.tone, 9))
    capped = findings if len(findings) <= limit else findings[:limit]
    return ExecutiveBrief(
        title=brief.title,
        verdict=brief.verdict,
        subtitle=brief.subtitle,
        tone=brief.tone,
        findings=capped,
    )


def _build_output_summary(
    result: LoadResult,
    rate_card: RateCard,
    shape_report: SessionShapeReport,
) -> OutputSummary | None:
    """Answer "what did this spend produce?" from local git + tool evidence.

    Returns ``None`` when there is neither git linkage nor classified tool
    activity, so the renderer drops the section rather than showing zeros.
    Every figure is sourced from logs already on disk. The function is pure:
    no network, no git shell-out (git SHAs are read from parsed events).
    """
    if not result.events:
        return None

    commit_cost: dict[str, Decimal] = defaultdict(Decimal)
    linked = Decimal("0")
    total = Decimal("0")
    for event in result.events:
        cost, _, _ = event_cost(rate_card, event)
        total += cost.cost_usd
        sha = event.thread.git_sha
        if sha:
            commit_cost[sha] += cost.cost_usd
            linked += cost.cost_usd

    commits_touched = len(commit_cost)
    has_git = commits_touched > 0
    cost_per_commit = float(linked / commits_touched) if commits_touched else 0.0
    linked_pct = float(linked / total) if total > 0 else 0.0

    edits = diagnostics = exploration = classified = 0
    for name, count in shape_report.tool_use.per_tool:
        if name in EXECUTION_TOOLS:
            edits += count
            classified += count
        elif name in DIAGNOSTIC_TOOLS:
            diagnostics += count
            classified += count
        elif name in EXPLORATION_TOOLS:
            exploration += count
            classified += count

    if not has_git and classified == 0:
        return None

    def _share(part: int) -> float:
        return (part / classified) if classified else 0.0

    if not has_git:
        caveat = (
            "No git history recorded in this window, so spend can't be tied to "
            "commits. The edit-vs-diagnostic mix below is still measured from "
            "tool calls."
        )
    else:
        caveat = (
            "Cost per commit divides git-linked spend by commits touched. It is "
            "a rough unit cost, not a per-commit invoice. Unlinked spend is "
            "exploration, planning, or work that never reached a commit, not "
            "automatically waste."
        )

    return OutputSummary(
        commits_touched=commits_touched,
        cost_per_commit_usd=cost_per_commit,
        linked_cost_usd=float(linked),
        linked_cost_pct=linked_pct,
        edit_share=_share(edits),
        diagnostic_share=_share(diagnostics),
        exploration_share=_share(exploration),
        classified_tool_calls=classified,
        has_git=has_git,
        caveat=caveat,
    )


def _build_budget_rows(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    budget_config: dict[str, Any] | None,
) -> list[BudgetRow]:
    """Translate ``evaluate_budgets`` output into renderer-ready burn rows.

    Filters to cost-denominated budgets (the §08 section is a dollar burn
    view). Returns an empty list when no budgets are configured — the renderer
    then hides the section entirely.
    """
    raw = (budget_config or {}).get("budgets") or {}
    try:
        budgets = parse_budgets_table(raw if isinstance(raw, dict) else {})
    except ValueError:
        return []
    if not budgets:
        return []

    from caliper.timeutil import load_timezone

    now = options.end.astimezone(load_timezone(options.timezone))
    windows = current_period_intervals(now)
    usage = usage_for_periods(result.events, options, rate_card, now, windows=windows)
    alerts = evaluate_budgets(budgets, usage)
    rows: list[BudgetRow] = []
    # Deterministic display order regardless of config order.
    period_order = {"daily": 0, "weekly": 1, "monthly": 2}
    for alert in sorted(alerts, key=lambda a: period_order.get(a.budget.period, 9)):
        if alert.budget.metric != "cost_usd":
            continue  # the §08 burn bar is dollars; token budgets stay in impact_cards
        if alert.severity == SEVERITY_BREACH:
            tone = "critical"
        elif alert.severity == SEVERITY_WARN:
            tone = "warn"
        else:
            tone = "good"
        warn_dollars = alert.budget.limit * float(alert.budget.warn_at)
        rows.append(
            BudgetRow(
                period=alert.budget.period,
                spent=float(alert.used),
                cap=float(alert.budget.limit),
                warn=warn_dollars,
                tone=tone,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


def _build_window(options: RuntimeOptions, result: LoadResult) -> WindowMeta:
    start = options.start.astimezone(dt.UTC).date()
    end = options.end.astimezone(dt.UTC).date()
    days = max(1, (end - start).days)
    label = f"Last {days} day{'s' if days != 1 else ''}"
    range_str = f"{start.isoformat()} → {end.isoformat()}"
    vendors_active = sorted({event.vendor for event in result.events if event.vendor})
    vendor_count_total = max(len(vendors_active), KNOWN_VENDOR_COUNT)
    return WindowMeta(
        start=start.isoformat(),
        end=end.isoformat(),
        label=label,
        range=range_str,
        timezone=options.timezone or "UTC",
        vendors_active=vendors_active,
        vendor_count_total=vendor_count_total,
    )


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------


def _build_totals(
    *,
    total: Aggregate,
    shape_report: SessionShapeReport,
    daily_points: list[DailyPoint],
    daily_session_count: list[int],
    daily_cache_rate: list[float],
    deltas: tuple[float | None, float | None, float | None, float | None],
) -> Totals:
    cost = float(total.costs.cost_usd)
    cache_savings = float(total.cache_savings.cost_usd)
    tokens = total.totals
    input_tokens = tokens.input_tokens
    cached = tokens.cached_input_tokens
    cache_hit_rate = (cached / input_tokens) if input_tokens else 0.0
    delta_cost, delta_cache, delta_tokens, delta_sessions = deltas
    return Totals(
        cost_usd=cost,
        events=tokens.events,
        cache_savings_usd=cache_savings,
        cache_hit_rate=cache_hit_rate,
        total_tokens=tokens.total_tokens,
        cached_input_tokens=cached,
        uncached_input_tokens=tokens.uncached_input_tokens,
        output_tokens=tokens.output_tokens,
        sessions=len(total.session_ids) or shape_report.total_sessions,
        turns=shape_report.total_turns,
        tools_per_turn=shape_report.tools_per_turn,
        delta_cost_pct=delta_cost,
        delta_cache_pct=delta_cache,
        delta_tokens_pct=delta_tokens,
        delta_sessions_pct=delta_sessions,
        daily_cost_sparkline=[float(p.cost_usd) for p in daily_points],
        daily_cache_sparkline=daily_cache_rate,
        daily_token_sparkline=[float(p.events) for p in daily_points],
        daily_session_sparkline=[float(n) for n in daily_session_count],
    )


def _daily_cache_sparkline(
    result: LoadResult,
    options: RuntimeOptions,
    daily_points: list[DailyPoint],
) -> list[float]:
    """Per-day cached-input share, zero-filled across the window.

    Per-day = ``cached_input_tokens / input_tokens`` computed from raw
    events grouped by local-tz day. A day with no input tokens (or no
    events at all) reports ``0.0``. The returned list length matches
    ``daily_points`` so the sparkline lines up with the cost chart.
    """
    from caliper.timeutil import day_key, load_timezone

    if not daily_points:
        return []
    tz = load_timezone(options.timezone)
    cached_by_day: dict[str, int] = {}
    input_by_day: dict[str, int] = {}
    for event in result.events:
        key = day_key(event.timestamp, tz)
        usage = event.usage
        cached_by_day[key] = cached_by_day.get(key, 0) + usage.cached_input_tokens
        input_by_day[key] = input_by_day.get(key, 0) + usage.input_tokens
    out: list[float] = []
    for point in daily_points:
        inp = input_by_day.get(point.day, 0)
        if inp == 0:
            out.append(0.0)
            continue
        out.append(cached_by_day.get(point.day, 0) / inp)
    return out


def _daily_session_counts(result: LoadResult, options: RuntimeOptions) -> list[int]:
    """Distinct session IDs per local-tz day, zero-filled across the window."""
    from caliper.timeutil import day_key, load_timezone

    tz = load_timezone(options.timezone)
    by_day: dict[str, set[str]] = {}
    for event in result.events:
        key = day_key(event.timestamp, tz)
        by_day.setdefault(key, set()).add(event.session_id)
    start = options.start.astimezone(tz).date()
    end = options.end.astimezone(tz).date()
    out: list[int] = []
    day = start
    while day < end:
        out.append(len(by_day.get(day.isoformat(), set())))
        day = day + dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Period-over-period deltas
# ---------------------------------------------------------------------------


def _compute_period_deltas(
    options: RuntimeOptions,
    total: Aggregate,
    shape_report: SessionShapeReport,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Return (Δcost, Δcache, Δtokens, Δsessions) vs. the prior equal window.

    Runs `load_usage()` for the prior window. The parse cache makes this
    cheap on warm runs.
    """
    span = options.end - options.start
    prior_options = dataclasses.replace(
        options,
        start=options.start - span,
        end=options.start,
    )
    try:
        prior_result = load_usage(prior_options)
    except Exception:
        # Don't let prior-window load failures kill the dashboard.
        return (None, None, None, None)

    prior_total = aggregate_total(prior_result, prior_options)
    prior_shape = compute_session_shape(prior_result)

    def _ratio(curr: float, prev: float) -> float | None:
        if prev == 0:
            return None
        return (curr - prev) / prev

    cost = float(total.costs.cost_usd)
    prior_cost = float(prior_total.costs.cost_usd)

    cur_cache_rate = (
        total.totals.cached_input_tokens / total.totals.input_tokens
        if total.totals.input_tokens
        else 0.0
    )
    prior_cache_rate = (
        prior_total.totals.cached_input_tokens / prior_total.totals.input_tokens
        if prior_total.totals.input_tokens
        else 0.0
    )

    cur_tokens = total.totals.total_tokens
    prior_tokens = prior_total.totals.total_tokens

    cur_sessions = len(total.session_ids) or shape_report.total_sessions
    prior_sessions = len(prior_total.session_ids) or prior_shape.total_sessions

    return (
        _ratio(cost, prior_cost),
        _ratio(cur_cache_rate, prior_cache_rate),
        _ratio(cur_tokens, prior_tokens),
        _ratio(cur_sessions, prior_sessions),
    )


# ---------------------------------------------------------------------------
# Daily series (zero-filled, with dominant work-shape tag)
# ---------------------------------------------------------------------------


def _build_daily(
    aggregates: list[Aggregate],
    shape_report: SessionShapeReport,
    options: RuntimeOptions,
) -> list[DailyPoint]:
    from caliper.timeutil import load_timezone

    tz = load_timezone(options.timezone)
    by_key = {agg.label: agg for agg in aggregates}
    shape_by_day = {item.day: item.category for item in shape_report.daily}

    start = options.start.astimezone(tz).date()
    end = options.end.astimezone(tz).date()
    out: list[DailyPoint] = []
    day = start
    while day < end:
        key = day.isoformat()
        agg = by_key.get(key)
        cost = float(agg.costs.cost_usd) if agg else 0.0
        events = agg.totals.events if agg else 0
        shape = _SHAPE_NAME_MAP.get(shape_by_day.get(key, CATEGORY_NONE), "no-tools")
        out.append(DailyPoint(day=key, cost_usd=cost, events=events, shape=shape))
        day = day + dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Rolling 7 / 30 / 90 day usage windows
# ---------------------------------------------------------------------------


def _build_usage_windows(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
) -> list[UsageWindow]:
    out: list[UsageWindow] = []
    end = options.end
    windows = [(f"Last {days} days", end - dt.timedelta(days=days)) for days in ROLLING_USAGE_DAYS]
    aggregates, _total = aggregate_overview_windows(
        result,
        options,
        windows,
        rate_card=rate_card,
    )
    daily_by_day = {agg.label: agg for agg in aggregate_daily(result, options, rate_card=rate_card)}
    active_days = _active_days_by_window(result, options, windows)
    for days, total in zip(ROLLING_USAGE_DAYS, aggregates, strict=True):
        start = end - dt.timedelta(days=days)
        window_options = dataclasses.replace(options, start=start, end=end)
        daily_cost, daily_tokens = _daily_window_sparklines_from_aggregates(
            daily_by_day,
            window_options,
        )
        input_tokens = total.totals.input_tokens
        cache_hit_rate = total.totals.cached_input_tokens / input_tokens if input_tokens else 0.0
        out.append(
            UsageWindow(
                label=f"Last {days} days",
                days=days,
                start=start.astimezone(dt.UTC).date().isoformat(),
                end=end.astimezone(dt.UTC).date().isoformat(),
                range=(
                    f"{start.astimezone(dt.UTC).date().isoformat()} → "
                    f"{end.astimezone(dt.UTC).date().isoformat()}"
                ),
                cost_usd=float(total.costs.cost_usd),
                total_tokens=total.totals.total_tokens,
                events=total.totals.events,
                sessions=len(total.session_ids),
                cache_hit_rate=cache_hit_rate,
                active_days=len(active_days[days]),
                daily_cost_sparkline=daily_cost,
                daily_token_sparkline=daily_tokens,
            )
        )
    return out


def _scoped_result(result: LoadResult, *, start: dt.datetime, end: dt.datetime) -> LoadResult:
    events = [event for event in result.events if start <= event.timestamp < end]
    samples = [sample for sample in result.rate_limit_samples if start <= sample.timestamp < end]
    return dataclasses.replace(result, events=events, rate_limit_samples=samples)


def _daily_window_sparklines_from_aggregates(
    daily_by_day: dict[str, Aggregate],
    options: RuntimeOptions,
) -> tuple[list[float], list[float]]:
    from caliper.timeutil import load_timezone

    tz = load_timezone(options.timezone)
    day = options.start.astimezone(tz).date()
    end = options.end.astimezone(tz).date()
    cost: list[float] = []
    tokens: list[float] = []
    while day < end:
        key = day.isoformat()
        agg = daily_by_day.get(key)
        cost.append(float(agg.costs.cost_usd) if agg else 0.0)
        tokens.append(float(agg.totals.total_tokens) if agg else 0.0)
        day = day + dt.timedelta(days=1)
    return cost, tokens


def _active_days_by_window(
    result: LoadResult,
    options: RuntimeOptions,
    windows: list[tuple[str, dt.datetime]],
) -> dict[int, set[str]]:
    from caliper.timeutil import load_timezone

    tz = load_timezone(options.timezone)
    out = {days: set() for days in ROLLING_USAGE_DAYS}
    for event in result.events:
        day = event.timestamp.astimezone(tz).date().isoformat()
        for days, (_label, start) in zip(ROLLING_USAGE_DAYS, windows, strict=True):
            if start <= event.timestamp < options.end:
                out[days].add(day)
    return out


def _active_day_count(events, options: RuntimeOptions) -> int:
    from caliper.timeutil import load_timezone

    tz = load_timezone(options.timezone)
    return len({event.timestamp.astimezone(tz).date().isoformat() for event in events})


# ---------------------------------------------------------------------------
# Session shape (handoff version)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Model rows
# ---------------------------------------------------------------------------


def _build_model_rows(
    aggregates: list[Aggregate],
    *,
    daily_by_model: dict[str, list[float]] | None = None,
) -> list[ModelRow]:
    rows: list[ModelRow] = []
    daily_by_model = daily_by_model or {}
    for agg in aggregates:
        if agg.totals.events == 0:
            continue
        model = next(iter(agg.models), "") or "unknown"
        tier = next(iter(agg.service_tiers), "") or "—"
        vendor = next(iter(agg.model_vendors), "") or model_vendor(model)
        input_tokens = agg.totals.input_tokens
        cache_hit_rate = agg.totals.cached_input_tokens / input_tokens if input_tokens else 0.0
        sparkline = list(daily_by_model.get(model, ()))
        rows.append(
            ModelRow(
                vendor=vendor,
                model=model,
                tier=tier,
                cost_usd=float(agg.costs.cost_usd),
                events=agg.totals.events,
                tokens=agg.totals.total_tokens,
                cache_hit_rate=cache_hit_rate,
                daily_cost_sparkline=sparkline,
            )
        )
    return sorted(
        rows,
        key=lambda row: (-row.cost_usd, -row.tokens, -row.events, row.vendor, row.model, row.tier),
    )[:12]


# ---------------------------------------------------------------------------
# Project rows
# ---------------------------------------------------------------------------


def _build_project_rows(
    aggregates: list[Aggregate],
    result: LoadResult,
    *,
    show_paths: bool,
    options: RuntimeOptions,
    daily_by_project: dict[str, list[float]],
    forecast_bands: dict[str, tuple[float, float, str]] | None = None,
) -> list[ProjectRow]:
    """Map our project aggregates + per-project tool counters into rows.

    Project aggregates are keyed by full `cwd`. We derive per-project
    tool counts directly from the LoadResult events keyed by the same
    full path so two repos with the same basename never share a tool
    list.
    """
    from collections import Counter

    from caliper.models import project_name_from_path
    from caliper.timeutil import load_timezone

    tz = load_timezone(options.timezone)
    tools_by_path: dict[str, Counter[str]] = {}
    active_days_by_path: dict[str, set[dt.date]] = {}
    for event in result.events:
        path = event.thread.cwd or UNKNOWN_PROJECT
        active_days_by_path.setdefault(path, set()).add(event.timestamp.astimezone(tz).date())
        if event.turn_facts is None:
            continue
        bucket = tools_by_path.setdefault(path, Counter())
        for tool_name in event.turn_facts.tool_names:
            bucket[tool_name] += 1

    start_day = options.start.astimezone(tz).date()
    end_day = options.end.astimezone(tz).date()
    window_days = max(1, (end_day - start_day).days)
    rows: list[ProjectRow] = []
    for agg in aggregates:
        if agg.totals.events == 0:
            continue
        path_str = agg.label
        name = project_name_from_path(path_str) if path_str else UNKNOWN_PROJECT
        series = daily_by_project.get(path_str, [0.0] * window_days)
        if len(series) < window_days:
            series = series + [0.0] * (window_days - len(series))
        active_days = len(active_days_by_path.get(path_str, set()))
        daily_mean = float(agg.costs.cost_usd) / window_days
        projected_30d = daily_mean * 30.0
        trend_label, trend_tone = _project_trend_label(series)
        last_seen = (
            agg.last_seen.astimezone(tz).strftime("%Y-%m-%d %H:%M")
            if agg.last_seen is not None
            else ""
        )
        top_tools_raw = sorted(
            tools_by_path.get(path_str, Counter()).items(),
            key=lambda item: (-item[1], item[0]),
        )[:3]
        top_tools = [
            ToolCount(name=tname, count=count, category=tool_category(tname))  # type: ignore[arg-type]
            for tname, count in top_tools_raw
        ]
        band = (forecast_bands or {}).get(path_str)
        if band is not None:
            low, high, confidence = band
        else:
            low, high, confidence = 0.0, 0.0, ""
        rows.append(
            ProjectRow(
                name=name,
                path=path_str if show_paths else None,
                cost_usd=float(agg.costs.cost_usd),
                events=agg.totals.events,
                sessions=len(agg.session_ids),
                top_tools=top_tools,
                active_days=active_days,
                last_seen=last_seen,
                daily_mean_cost_usd=daily_mean,
                projected_30d_cost_usd=projected_30d,
                trend_label=trend_label,
                trend_tone=trend_tone,  # type: ignore[arg-type]
                daily_cost_sparkline=series,
                projected_30d_low=low,
                projected_30d_high=high,
                forecast_confidence=confidence,
            )
        )
    return sorted(
        rows,
        key=lambda row: (-row.cost_usd, -row.events, -row.sessions, row.name, row.path or ""),
    )[:15]


def _project_trend_label(series: list[float]) -> tuple[str, str]:
    """Compare the latest seven selected-window days with the prior seven.

    The label is intentionally conservative: without two complete
    seven-day slices, the dashboard says so instead of implying a trend.
    """
    if len(series) < 14:
        return "needs 14d history", "neutral"
    recent = series[-7:]
    prior = series[-14:-7]
    recent_mean = sum(recent) / 7.0
    prior_mean = sum(prior) / 7.0
    if recent_mean <= 0 and prior_mean <= 0:
        return "flat vs prior 7d", "neutral"
    if prior_mean <= 0:
        return "new activity in last 7d", "warn"
    delta = (recent_mean - prior_mean) / prior_mean
    if abs(delta) < 0.05:
        return "flat vs prior 7d", "neutral"
    return f"{_format_signed_pct(delta)} vs prior 7d", ("warn" if delta > 0 else "good")


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


def _build_insights(
    result: LoadResult,
    rate_card: Any,
    *,
    total: Aggregate,
    projects: list[Aggregate],
    daily: list[Aggregate],
    audit_findings: list[Any],
    inefficiency_findings: list[Any],
) -> list[Insight]:
    raw = build_insights_from(
        result=result,
        rate_card=rate_card,
        total=total,
        projects=projects,
        daily=daily,
        audit_findings=audit_findings,
    )
    raw.extend(_inefficiency_insight(item) for item in inefficiency_findings[:3])
    raw = sorted(raw, key=lambda item: (-item.priority, item.title))[:10]
    return [
        Insight(
            severity=_SEVERITY_MAP.get(item.severity, "info"),  # type: ignore[arg-type]
            title=item.title,
            detail=item.detail,
            impact=item.impact_label or None,
            evidence_metrics=dict(getattr(item, "evidence_metrics", {}) or {}),
        )
        for item in raw
    ]


# ---------------------------------------------------------------------------
# Impact cards
# ---------------------------------------------------------------------------


def _build_impact_cards(
    *,
    result: LoadResult,
    rolling_result: LoadResult,
    options: RuntimeOptions,
    rolling_options: RuntimeOptions,
    total: Aggregate,
    by_model: list[ModelRow],
    by_project: list[ProjectRow],
    rate_card: RateCard,
    budget_config: dict[str, Any] | None,
) -> list[ImpactCard]:
    cards = [
        _cost_driver_card(total, by_project, by_model),
        _budget_risk_card(rolling_result, rolling_options, rate_card, budget_config),
        _cache_leverage_card(total),
        _usage_behavior_card(result, options, total),
        _dedupe_card(rolling_result),
    ]
    return sorted(cards, key=_impact_card_sort_key)


_IMPACT_LABEL_ORDER = {
    "Budget risk": 0,
    "Cost driver": 1,
    "Cache discount": 2,
    "Usage rhythm": 3,
    "Dedupe": 4,
}
_IMPACT_TONE_ORDER = {"critical": 0, "warn": 1, "good": 2, "neutral": 3}


def _impact_card_sort_key(card: ImpactCard) -> tuple[int, int, str]:
    return (
        _IMPACT_LABEL_ORDER.get(card.label, 99),
        _IMPACT_TONE_ORDER.get(card.tone, 3),
        card.label,
    )


def _cost_driver_card(
    total: Aggregate,
    by_project: list[ProjectRow],
    by_model: list[ModelRow],
) -> ImpactCard:
    if not total.totals.events:
        return ImpactCard(
            label="Cost driver",
            value="No selected usage",
            detail="The selected dashboard window has no events.",
        )
    total_cost = float(total.costs.cost_usd)
    if by_project:
        top_project = max(by_project, key=lambda row: row.cost_usd)
        share = top_project.cost_usd / total_cost if total_cost else 0.0
        return ImpactCard(
            label="Cost driver",
            value=top_project.name,
            detail=(
                f"{_format_money(top_project.cost_usd)} · "
                f"{_format_pct_round(share)} of selected-window cost"
            ),
            tone="warn" if share >= 0.5 else "neutral",
        )
    if by_model:
        top_model = max(by_model, key=lambda row: row.cost_usd)
        share = top_model.cost_usd / total_cost if total_cost else 0.0
        return ImpactCard(
            label="Cost driver",
            value=_humanize_model(top_model.model),
            detail=(
                f"{_format_money(top_model.cost_usd)} · "
                f"{_format_pct_round(share)} of selected-window cost"
            ),
            tone="warn" if share >= 0.5 else "neutral",
        )
    return ImpactCard(
        label="Cost driver",
        value="Unattributed",
        detail=f"{_format_money(total_cost)} selected-window cost.",
    )


def _budget_risk_card(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    budget_config: dict[str, Any] | None,
) -> ImpactCard:
    try:
        raw = (budget_config or {}).get("budgets") or {}
        budgets = parse_budgets_table(raw if isinstance(raw, dict) else {})
    except ValueError as exc:
        return ImpactCard(
            label="Budget risk",
            value="Check config",
            detail=str(exc),
            tone="warn",
        )
    if not budgets:
        return ImpactCard(
            label="Budget risk",
            value="No budgets",
            detail="Add a [budgets] table to show daily, weekly, or monthly risk.",
        )

    from caliper.timeutil import load_timezone

    now = options.end.astimezone(load_timezone(options.timezone))
    windows = current_period_intervals(now)
    usage = usage_for_periods(result.events, options, rate_card, now, windows=windows)
    alerts = evaluate_budgets(budgets, usage)
    if not alerts:
        return ImpactCard(
            label="Budget risk",
            value="No budgets",
            detail="Add a [budgets] table to show daily, weekly, or monthly risk.",
        )
    worst = max_severity(alerts)
    top = max(alerts, key=lambda alert: alert.used_percent)
    used = (
        _format_money(top.used)
        if top.budget.metric == "cost_usd"
        else _format_tokens(int(top.used))
    )
    limit = (
        _format_money(top.budget.limit)
        if top.budget.metric == "cost_usd"
        else _format_tokens(int(top.budget.limit))
    )
    tone = "critical" if worst == SEVERITY_BREACH else "warn" if worst == SEVERITY_WARN else "good"
    metric = "cost" if top.budget.metric == "cost_usd" else "tokens"
    return ImpactCard(
        label="Budget risk",
        value=f"{top.used_percent:.0f}%",
        detail=f"{top.budget.period} {metric}: {used} of {limit}",
        tone=tone,
    )


def _cache_leverage_card(total: Aggregate) -> ImpactCard:
    input_tokens = total.totals.input_tokens
    cache_hit = total.totals.cached_input_tokens / input_tokens if input_tokens else 0.0
    savings = float(total.cache_savings.cost_usd)
    if savings > 0:
        return ImpactCard(
            label="Cache discount",
            value=_format_money(savings),
            detail=f"{_format_pct(cache_hit)} cached-input share, vs. the full input rate.",
            tone="good",
        )
    return ImpactCard(
        label="Cache discount",
        value="None",
        detail=f"{_format_pct(cache_hit)} cached-input share in the selected window.",
    )


def _usage_behavior_card(
    result: LoadResult,
    options: RuntimeOptions,
    total: Aggregate,
) -> ImpactCard:
    active_days = _active_day_count(result.events, options)
    if not result.events:
        return ImpactCard(
            label="Usage rhythm",
            value="No activity",
            detail="No events landed in the selected dashboard window.",
        )
    peak = _peak_hour(result, options)
    day_word = "day" if active_days == 1 else "days"
    return ImpactCard(
        label="Usage rhythm",
        value=f"{active_days} active {day_word}",
        detail=(
            f"Peak hour {peak}; {len(total.session_ids):,} sessions; "
            f"{_format_tokens(total.totals.total_tokens)} tokens."
        ),
    )


def _dedupe_card(result: LoadResult) -> ImpactCard:
    duplicates = result.duplicates + result.rate_limit_sample_duplicates
    return ImpactCard(
        label="Dedupe",
        value=f"{duplicates:,} skipped",
        detail="Rolling windows use parser-deduped usage events.",
        tone="good" if duplicates else "neutral",
    )


def _peak_hour(result: LoadResult, options: RuntimeOptions) -> str:
    from caliper.timeutil import load_timezone

    tz = load_timezone(options.timezone)
    by_hour: dict[int, int] = {}
    for event in result.events:
        hour = event.timestamp.astimezone(tz).hour
        by_hour[hour] = by_hour.get(hour, 0) + 1
    if not by_hour:
        return "—"
    return _format_hour_12(max(by_hour.items(), key=lambda kv: kv[1])[0])


def _format_money(n: float | int) -> str:
    amount = float(n)
    if amount == 0:
        return "$0"
    if abs(amount) >= 1000:
        return f"${round(amount):,}"
    return f"${amount:.2f}"


def _format_pct(p: float) -> str:
    return f"{p * 100:.1f}%"


def _format_pct_round(p: float) -> str:
    return f"{round(p * 100)}%"


# ---------------------------------------------------------------------------
# Command center + drilldown analytics
# ---------------------------------------------------------------------------


def _build_advisor_recommendations(
    result: LoadResult,
    rate_card: RateCard,
    options: RuntimeOptions | None = None,
    *,
    audit_findings: list[Any] | None = None,
) -> list[AdvisorRecommendation]:
    """Surface the highest-value recommendations in canonical rank order.

    Single source of truth: the same quantified-inefficiency engine
    (:func:`caliper.efficiency.run_audit` + ``rank_recommendations``) that
    powers ``caliper recommend`` / ``caliper exec``, so the dashboard
    verdict's "top fix" and "Fixable $X" reconcile with those commands.

    The arbitrage re-pricing sweep (``caliper advise`` / ``caliper whatif``)
    is deliberately *not* merged here: its events carry no stable ids, so
    folding it in would double-count dollars against the finders above.
    Rows are returned already ranked; callers must not re-sort by savings.
    """
    if not result.events:
        return []
    return _efficiency_advisor_rows(result, rate_card, options, audit_findings=audit_findings)


def _efficiency_advisor_rows(
    result: LoadResult,
    rate_card: RateCard,
    options: RuntimeOptions | None,
    *,
    audit_findings: list[Any] | None = None,
) -> list[AdvisorRecommendation]:
    """Adapt :mod:`caliper.efficiency` findings into advisor rows."""
    if options is None:
        return []
    try:
        findings = (
            audit_findings if audit_findings is not None else run_audit(result, options, rate_card)
        )
    except Exception:
        return []
    recs = rank_recommendations(findings, top=5)
    rows: list[AdvisorRecommendation] = []
    confidence_floor = {"high": 0.9, "medium": 0.7, "low": 0.55}
    for rec in recs:
        savings = float(rec.impact_usd_exact)
        if savings <= 0:
            continue
        action = rec.commands[0] if rec.commands else "caliper audit"
        rows.append(
            AdvisorRecommendation(
                title=rec.payback_action,
                value=_format_money(savings),
                detail=rec.detail,
                action=action,
                confidence=confidence_floor.get(rec.confidence, 0.6),
                events=0,
                sessions=0,
                tone="good",
                savings_usd=savings,
            )
        )
    return rows


def _build_top_sessions(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    *,
    session_aggregates: list[Aggregate] | None = None,
) -> list[SessionRow]:
    """Cost/token/tool outliers, deduped by upstream session identity."""
    if not result.events:
        return []
    from caliper.models import project_name_from_path

    tool_calls_by_session: dict[str, int] = {}
    for event in result.events:
        if event.turn_facts is None:
            continue
        tool_calls_by_session[event.session_id] = (
            tool_calls_by_session.get(event.session_id, 0) + event.turn_facts.tool_use_count
        )

    rows: list[SessionRow] = []
    aggregates = session_aggregates or aggregate_sessions(result, options, rate_card=rate_card)
    for agg in aggregates[:10]:
        raw_label = _session_label(agg.label, agg.key)
        label = _human_session_label(
            agg.first_seen,
            options.timezone,
            fallback=raw_label,
        )
        started = _human_datetime(agg.first_seen, options.timezone, fallback="")
        if started == label:
            started = (
                agg.first_seen.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
                if agg.first_seen
                else ""
            )
        project = " · ".join(sorted(agg.project_names)) if agg.project_names else UNKNOWN_PROJECT
        if project == UNKNOWN_PROJECT and agg.project_paths:
            project = project_name_from_path(sorted(agg.project_paths)[0])
        tools = tool_calls_by_session.get(agg.key, 0)
        rows.append(
            SessionRow(
                label=label,
                started_at=started,
                project=project,
                cost_usd=float(agg.costs.cost_usd),
                total_tokens=agg.totals.total_tokens,
                events=agg.totals.events,
                tool_calls=tools,
                models=sorted(agg.models)[:3],
                reason=_session_outlier_reason(agg, tools),
            )
        )
    return sorted(
        rows,
        key=lambda row: (
            -row.cost_usd,
            -row.total_tokens,
            -row.tool_calls,
            -row.events,
            row.started_at,
            row.label,
        ),
    )[:8]


def _session_label(label: str, key: str) -> str:
    if " | " in label:
        label = label.split(" | ", 1)[1]
    label = label.strip() or key
    if len(label) > 72:
        return f"{label[:69]}..."
    return label


def _session_outlier_reason(agg: Aggregate, tool_calls: int) -> str:
    if agg.long_context_events:
        return "long context"
    if tool_calls >= 25:
        return "tool-heavy"
    if agg.unknown_model_events or agg.unknown_tier_events:
        return "needs attribution"
    if agg.costs.cost_usd > 0:
        return "cost outlier"
    if agg.totals.total_tokens:
        return "token-heavy"
    return "high activity"


def _session_label_lookup(events: list[Any], timezone: str) -> dict[str, str]:
    return session_label_lookup(events, timezone)


def _human_session_label(
    value: dt.datetime | None,
    timezone: str,
    *,
    fallback: str,
) -> str:
    label = _human_datetime(value, timezone, fallback="")
    if label:
        return label
    return fallback


def _human_datetime(
    value: dt.datetime | None,
    timezone: str,
    *,
    fallback: str,
) -> str:
    return _format_human_datetime(value, timezone, fallback=fallback)


def _build_agent_rows(
    result: LoadResult,
    rate_card: RateCard,
    *,
    options: RuntimeOptions | None = None,
    attributions: list[Any] | None = None,
) -> list[AgentRow]:
    daily_by_agent = _per_agent_daily_cost(result, rate_card, options) if options else {}
    rows: list[AgentRow] = []
    source_rows = (
        attributions if attributions is not None else build_agent_attributions(result, rate_card)
    )
    for row in source_rows[:12]:
        rows.append(
            AgentRow(
                agent_id=row.agent_id,
                source_category=row.source_category,
                evidence_status=_evidence_literal(row.evidence_status),
                reason=row.reason,
                kind=row.kind,
                cost_usd=float(row.cost_usd),
                total_tokens=row.total_tokens,
                events=row.events,
                tool_calls=row.tool_calls,
                sessions=row.session_count,
                daily_cost_sparkline=daily_by_agent.get(row.agent_id, []),
            )
        )
    return rows


def _per_agent_daily_cost(
    result: LoadResult,
    rate_card: RateCard,
    options: RuntimeOptions,
) -> dict[str, list[float]]:
    """Per-agent daily cost dense series in local TZ."""
    from caliper.attribution import _agent_identity, _normalize_agent_id
    from caliper.timeutil import load_timezone

    tz = load_timezone(options.timezone)
    per_agent: dict[str, dict[dt.date, float]] = {}
    for event in result.events:
        identity = _agent_identity(event)
        if not identity:
            continue
        agent_id = (
            _normalize_agent_id(identity.get("agent_id", "")) if isinstance(identity, dict) else ""
        )
        if not agent_id:
            continue
        cost, _, _ = event_cost(rate_card, event)
        local = event.timestamp.astimezone(tz).date()
        bucket = per_agent.setdefault(agent_id, {})
        bucket[local] = bucket.get(local, 0.0) + float(cost.cost_usd)
    out: dict[str, list[float]] = {}
    for agent_id, by_day in per_agent.items():
        if not by_day:
            continue
        start, end = min(by_day), max(by_day)
        days = (end - start).days + 1
        series = [0.0] * days
        for day, value in by_day.items():
            series[(day - start).days] = value
        out[agent_id] = series
    return out


def _build_cohort_deltas(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    total: Aggregate,
) -> list[CohortDeltaRow]:
    """Side-by-side comparison vs. the prior equal-length window.

    Best-effort: returns ``[]`` when the prior window parses cleanly to zero
    activity (avoids meaningless 0→x deltas) or when the prior load fails.
    """
    span = options.end - options.start
    prior_options = dataclasses.replace(
        options,
        start=options.start - span,
        end=options.start,
    )
    try:
        prior = load_usage(prior_options)
    except Exception:
        return []
    prior_total = aggregate_total(prior, prior_options, rate_card=rate_card)
    if prior_total.totals.events == 0:
        return []

    def row(
        label: str,
        cur: float,
        prev: float,
        *,
        money: bool = False,
        pct: bool = False,
        high_bad: bool = True,
    ) -> CohortDeltaRow:
        delta_value = cur - prev
        delta_pct = None if prev == 0 else (cur - prev) / prev
        if money:
            cur_s = f"${cur:,.2f}"
            prev_s = f"${prev:,.2f}"
        elif pct:
            cur_s = f"{cur * 100:.1f}%"
            prev_s = f"{prev * 100:.1f}%"
        else:
            cur_s = f"{int(cur):,}"
            prev_s = f"{int(prev):,}"
        if delta_pct is None or abs(delta_pct) < 0.01:
            tone = "neutral"
        elif (delta_pct > 0) == high_bad:
            tone = "warn"
        else:
            tone = "good"
        return CohortDeltaRow(
            label=label,
            current_value=cur_s,
            previous_value=prev_s,
            delta_pct=delta_pct,
            delta_value=delta_value,
            tone=tone,  # type: ignore[arg-type]
        )

    cur_cache = (
        total.totals.cached_input_tokens / total.totals.input_tokens
        if total.totals.input_tokens
        else 0.0
    )
    prior_cache = (
        prior_total.totals.cached_input_tokens / prior_total.totals.input_tokens
        if prior_total.totals.input_tokens
        else 0.0
    )
    return [
        row(
            "Total cost",
            float(total.costs.cost_usd),
            float(prior_total.costs.cost_usd),
            money=True,
            high_bad=True,
        ),
        row(
            "Total tokens",
            total.totals.total_tokens,
            prior_total.totals.total_tokens,
            high_bad=True,
        ),
        row("Events", total.totals.events, prior_total.totals.events, high_bad=True),
        row(
            "Sessions",
            len(total.session_ids),
            len(prior_total.session_ids),
            high_bad=False,
        ),
        row("Cache hit rate", cur_cache, prior_cache, pct=True, high_bad=False),
    ]


def _build_skill_rows(
    result: LoadResult,
    rate_card: RateCard,
    *,
    attributions: list[Any] | None = None,
) -> list[SkillRow]:
    rows: list[SkillRow] = []
    source_rows = (
        attributions if attributions is not None else build_skill_attributions(result, rate_card)
    )
    for row in source_rows[:12]:
        rows.append(
            SkillRow(
                name=row.name,
                evidence_status=_evidence_literal(row.evidence_status),
                attribution_method=row.attribution_method,
                estimated_cost_usd=float(row.cost_usd),
                median_cost_per_invocation_usd=float(row.median_cost_per_invocation),
                total_tokens=row.total_tokens,
                invocations=row.invocation_count,
                sessions=row.session_count,
            )
        )
    return rows


def _build_inefficiency_rows(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    *,
    budget_config: dict[str, Any] | None,
    findings: list[Any] | None = None,
) -> list[InefficiencyRow]:
    rows: list[InefficiencyRow] = []
    prompt_rot_curve_data = _median_prompt_rot_curve(result)
    source_findings = findings
    if source_findings is None:
        source_findings = build_inefficiency_findings(
            result,
            options,
            rate_card,
            budget_config=budget_config,
        )
    for finding in source_findings[:12]:
        curve = prompt_rot_curve_data if finding.code == "PROMPT_ROT" else ()
        rows.append(
            InefficiencyRow(
                code=finding.code,
                severity=finding.severity,
                evidence_status=_evidence_literal(finding.evidence_status),
                title=finding.title,
                detail=finding.detail,
                action=finding.action,
                impact_usd=float(finding.impact_usd_exact),
                monthly_projected_savings_usd=float(finding.monthly_projected_savings_usd),
                confidence=finding.confidence,
                sample_size=finding.sample_size,
                baseline=finding.baseline,
                curve=curve,
            )
        )
    return rows


def _median_prompt_rot_curve(result: LoadResult) -> tuple[int, ...]:
    """Median per-turn input-token curve across the most rot-prone sessions.

    Aligns curves to a common length (truncating to the shortest), so a
    single SVG renders cleanly. Empty when no session has ≥3 turns.
    """
    from caliper.patterns import prompt_rot_curve, session_event_groups

    candidates: list[list[int]] = []
    for events in session_event_groups(result.events).values():
        if len(events) < 3:
            continue
        curve = prompt_rot_curve(events)
        if len(curve) < 3 or curve[0] <= 0:
            continue
        if max(curve) >= curve[0] * 2:
            candidates.append(curve)
    if not candidates:
        return ()
    min_len = min(len(c) for c in candidates)
    truncated = [c[:min_len] for c in candidates]
    median_curve: list[int] = []
    for idx in range(min_len):
        column = sorted(c[idx] for c in truncated)
        median_curve.append(column[len(column) // 2])
    return tuple(median_curve)


# ---------------------------------------------------------------------------
# Cache leverage by session — P7 power-up
# ---------------------------------------------------------------------------


def _build_cache_leverage(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    *,
    top_n: int = 8,
    session_aggregates: list[Aggregate] | None = None,
) -> list[CacheLeverageRow]:
    """Rank sessions by how much cache savings their cached input produced.

    ``savings_usd`` = cached input × (uncached input rate − cached input rate)
    so the chip reflects realised dollar avoidance, not raw token volumes.
    """
    if not result.events:
        return []
    session_aggs = session_aggregates or aggregate_sessions(result, options, rate_card=rate_card)
    rows: list[CacheLeverageRow] = []
    for agg in session_aggs:
        totals = agg.totals
        if not totals.cached_input_tokens:
            continue
        savings = float(
            getattr(agg, "cache_savings", None).cost_usd
            if getattr(agg, "cache_savings", None)
            else 0.0
        )
        if savings <= 0:
            continue
        denom = totals.cached_input_tokens + totals.input_tokens
        hit_rate = totals.cached_input_tokens / denom if denom else 0.0
        project = next(iter(agg.projects), "") if hasattr(agg, "projects") else ""
        rows.append(
            CacheLeverageRow(
                session_label=_human_session_label(
                    agg.first_seen,
                    options.timezone,
                    fallback=_session_label(agg.label, agg.key),
                ),
                project=project,
                savings_usd=savings,
                hit_rate=hit_rate,
                cached_input_tokens=totals.cached_input_tokens,
                uncached_input_tokens=totals.input_tokens,
            )
        )
    rows.sort(key=lambda r: -r.savings_usd)
    return rows[:top_n]


# ---------------------------------------------------------------------------
# Long-context input histogram — P10 power-up
# ---------------------------------------------------------------------------


_LC_BINS = (0, 1_000, 4_000, 16_000, 64_000, 200_000, 1_000_000)


def _build_long_context_histogram(
    result: LoadResult,
    rate_card: RateCard,
) -> LongContextHistogram | None:
    """Log-spaced histogram of per-event input tokens vs the LC threshold."""
    if not result.events:
        return None
    counts = [0] * len(_LC_BINS)
    total_cost = 0.0
    cost_above = 0.0
    events_above = 0
    threshold = 0
    for event in result.events:
        inp = event.usage.input_tokens or 0
        # Bin assignment — left-edge-inclusive.
        bucket = 0
        for idx, edge in enumerate(_LC_BINS):
            if inp >= edge:
                bucket = idx
        counts[bucket] += 1
        cost, _, _ = event_cost(rate_card, event)
        cost_value = float(cost.cost_usd)
        total_cost += cost_value
        normalized_model = normalize_model(event.model)
        card = rate_card.catalog_cards.get(normalized_model) or MODELS_BY_NAME.get(normalized_model)
        rule = getattr(card, "long_context", None) if card else None
        model_threshold = getattr(rule, "threshold", 0) if rule else 0
        if model_threshold:
            threshold = max(threshold, int(model_threshold))
        if model_threshold and inp > model_threshold:
            events_above += 1
            cost_above += cost_value
    total_events = sum(counts)
    if total_events == 0:
        return None
    return LongContextHistogram(
        bins=tuple(_LC_BINS),
        counts=tuple(counts),
        threshold_tokens=threshold or 200_000,
        share_above_threshold=events_above / total_events if total_events else 0.0,
        cost_share_above_threshold=cost_above / total_cost if total_cost else 0.0,
        total_events=total_events,
    )


def _build_anomaly_rows(
    *,
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    daily_aggregates: list[Aggregate],
) -> list[AnomalyRow]:
    raw = detect_actionable_anomalies(
        result.events,
        rate_card,
        options.timezone,
        daily=daily_aggregates,
    )
    session_labels = _session_label_lookup(result.events, options.timezone)
    rows: list[AnomalyRow] = []
    for item in raw:
        label = _anomaly_label(item.kind, item.label, show_paths=options.show_paths)
        if item.kind == "session_spike":
            label = session_labels.get(
                item.label,
                _human_session_label(item.timestamp, options.timezone, fallback=label),
            )
        rows.append(
            AnomalyRow(
                kind=_anomaly_kind_label(item.kind),
                label=label,
                timestamp=_human_datetime(item.timestamp, options.timezone, fallback=""),
                observed_usd=item.observed,
                baseline_usd=item.baseline_center,
                baseline_scale_usd=item.baseline_scale,
                z_score=item.z_score,
                impact_usd=float(item.impact_usd_exact),
                evidence_status="estimated",
                tone="critical" if item.z_score >= 5.0 else "warn",
                comparison_scope=item.comparison_scope,
                baseline_sample_count=item.baseline_sample_count,
                reason=item.reason,
                impact_percent=item.impact_percent,
            )
        )
    return sorted(rows, key=lambda row: (-row.impact_usd, -row.z_score, row.kind, row.label))[:12]


def _anomaly_kind_label(kind: str) -> str:
    return {
        "daily_spike": "Daily spike",
        "model_day_spike": "Model-day spike",
        "project_day_spike": "Project-day spike",
        "session_spike": "Session spike",
    }.get(kind, kind.replace("_", " ").title())


def _anomaly_label(kind: str, label: str, *, show_paths: bool) -> str:
    if show_paths or kind != "project_day_spike" or " / " not in label:
        return label
    from caliper.models import project_name_from_path

    project, day = label.rsplit(" / ", 1)
    return f"{project_name_from_path(project)} / {day}"


def _evidence_literal(value: str):
    if value in {"exact", "estimated", "partial", "unsupported"}:
        return value
    return "partial"


def _daily_cost_sparkline_by_key(result, options, rate_card, key_fn) -> dict[str, list[float]]:
    from caliper.timeutil import load_timezone

    tz = load_timezone(options.timezone)
    days: list[str] = []
    day = options.start.astimezone(tz).date()
    end = options.end.astimezone(tz).date()
    while day < end:
        days.append(day.isoformat())
        day = day + dt.timedelta(days=1)
    index = {key: i for i, key in enumerate(days)}
    out: dict[str, list[float]] = {}
    for event in result.events:
        event_day = event.timestamp.astimezone(tz).date().isoformat()
        pos = index.get(event_day)
        if pos is None:
            continue
        key, _label = key_fn(event)
        costs, _long_context, _unknown_model = event_cost(rate_card, event)
        out.setdefault(key, [0.0] * len(days))[pos] += float(costs.cost_usd)
    return out


def _build_rate_limit_pressure(result: LoadResult) -> RateLimitPressure:
    records = list(result.rate_limit_samples)
    for event in result.events:
        if (
            event.primary_used_percent is not None
            or event.secondary_used_percent is not None
            or event.rate_limit_reached_type
        ):
            records.append(event)
    if not records:
        return RateLimitPressure(
            sample_count=0,
            peak_primary_pct=None,
            peak_secondary_pct=None,
            latest_primary_pct=None,
            latest_secondary_pct=None,
            latest_limit_name="",
            latest_plan_type="",
            latest_resets_at="",
            reached_count=0,
        )

    latest = max(records, key=lambda item: item.timestamp)
    primary_values = [_percent_fraction(item.primary_used_percent) for item in records]
    secondary_values = [_percent_fraction(item.secondary_used_percent) for item in records]
    primary_values = [value for value in primary_values if value is not None]
    secondary_values = [value for value in secondary_values if value is not None]
    peak = max(primary_values + secondary_values, default=0.0)
    reached = sum(1 for item in records if getattr(item, "rate_limit_reached_type", ""))
    tone: str = "neutral"
    if reached or peak >= 0.95:
        tone = "critical"
    elif peak >= 0.75:
        tone = "warn"
    latest_reset = latest.primary_resets_at or latest.secondary_resets_at or ""
    forecasts = _build_rate_limit_forecast_bands(result)
    return RateLimitPressure(
        sample_count=len(records),
        peak_primary_pct=max(primary_values) if primary_values else None,
        peak_secondary_pct=max(secondary_values) if secondary_values else None,
        latest_primary_pct=_percent_fraction(latest.primary_used_percent),
        latest_secondary_pct=_percent_fraction(latest.secondary_used_percent),
        latest_limit_name=latest.limit_name or latest.limit_id or "",
        latest_plan_type=latest.plan_type or "",
        latest_resets_at=_stringify_reset(latest_reset),
        reached_count=reached,
        tone=tone,  # type: ignore[arg-type]
        forecasts=forecasts,
    )


# Map vendor ids to short display labels for per-source rate-limit panels.
_RATE_LIMIT_SOURCE_LABELS: dict[str, str] = {
    "openai-codex": "Codex",
    "claude-code": "Claude Code",
    "cursor": "Cursor",
    "aider": "Aider",
}


def _build_rate_limit_pressures_by_source(result: LoadResult) -> list[RateLimitPressure]:
    """One :class:`RateLimitPressure` per vendor that emitted samples.

    Returns an empty list when no records carry rate-limit data, so the
    renderer can fall back to the legacy single-pressure object cleanly.
    Ordering: Codex first, then Claude Code, then any other vendors
    alphabetically — stable across renders and matches how the rest of the
    dashboard lists sources.
    """
    by_source: dict[str, list] = {}
    for sample in result.rate_limit_samples:
        if (
            sample.primary_used_percent is None
            and sample.secondary_used_percent is None
            and not sample.rate_limit_reached_type
        ):
            continue
        by_source.setdefault(sample.vendor or "", []).append(sample)
    for event in result.events:
        if (
            event.primary_used_percent is None
            and event.secondary_used_percent is None
            and not event.rate_limit_reached_type
        ):
            continue
        by_source.setdefault(getattr(event, "vendor", "") or "", []).append(event)
    if not by_source:
        return []
    # Stable ordering: Codex, Claude Code, then alphabetical for the rest.
    priority = {"openai-codex": 0, "claude-code": 1}
    ordered_sources = sorted(by_source.keys(), key=lambda s: (priority.get(s, 2), s))
    out: list[RateLimitPressure] = []
    for source in ordered_sources:
        records = by_source[source]
        latest = max(records, key=lambda item: item.timestamp)
        primary_values = [_percent_fraction(item.primary_used_percent) for item in records]
        secondary_values = [_percent_fraction(item.secondary_used_percent) for item in records]
        primary_values = [v for v in primary_values if v is not None]
        secondary_values = [v for v in secondary_values if v is not None]
        peak = max(primary_values + secondary_values, default=0.0)
        reached = sum(1 for r in records if getattr(r, "rate_limit_reached_type", ""))
        if reached or peak >= 0.95:
            tone: str = "critical"
        elif peak >= 0.75:
            tone = "warn"
        else:
            tone = "neutral"
        latest_reset = latest.primary_resets_at or latest.secondary_resets_at or ""
        out.append(
            RateLimitPressure(
                sample_count=len(records),
                peak_primary_pct=max(primary_values) if primary_values else None,
                peak_secondary_pct=max(secondary_values) if secondary_values else None,
                latest_primary_pct=_percent_fraction(latest.primary_used_percent),
                latest_secondary_pct=_percent_fraction(latest.secondary_used_percent),
                latest_limit_name=latest.limit_name or latest.limit_id or "",
                latest_plan_type=latest.plan_type or "",
                latest_resets_at=_stringify_reset(latest_reset),
                reached_count=reached,
                tone=tone,  # type: ignore[arg-type]
                forecasts=(),
                source=source,
                source_label=_RATE_LIMIT_SOURCE_LABELS.get(source, source or ""),
            )
        )
    return out


def _build_rate_limit_forecast_bands(
    result: LoadResult,
) -> tuple[RateLimitForecastBand, ...]:
    samples = list(result.rate_limit_samples)
    if not samples:
        return ()
    raw = forecast_rate_limits(samples)
    bands: list[RateLimitForecastBand] = []
    for forecast in raw:
        bands.append(
            RateLimitForecastBand(
                window=forecast.window,
                limit_name=forecast.limit_name or forecast.limit_id or forecast.window,
                current_percent=forecast.current_percent,
                burn_rate_per_hour=forecast.burn_rate_per_hour,
                eta_low_hours=forecast.eta_low_hours,
                eta_mid_hours=forecast.eta_to_100_hours,
                eta_high_hours=forecast.eta_high_hours,
                confidence=forecast.confidence,
                samples=forecast.samples,
            )
        )
    return tuple(bands)


# ---------------------------------------------------------------------------
# Seasonality (cost-weighted hour × dow) — P1 power-up
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Portfolio 30/90-day outlook — P4 power-up
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Per-model forecast strip — P2 power-up
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Per-project forecast bands — P5 power-up
# ---------------------------------------------------------------------------


def _build_project_forecast_bands(
    project_aggregates: list[Aggregate],
    options: RuntimeOptions,
    daily_by_project: dict[str, list[float]],
) -> dict[str, tuple[float, float, str]]:
    """Per-project ±σ band + confidence chip keyed by project ``cwd``.

    Confidence:
      * "high"   when ≥14 days of activity,
      * "medium" when 7–13 days,
      * "low"    when 3–6 days (still emits a band),
      * ""       when <3 days (band omitted — sparse history).
    """
    if not project_aggregates:
        return {}

    def factory(agg: Aggregate) -> list[float]:
        return list(daily_by_project.get(agg.label, []))

    raw = forecast_project_burn(project_aggregates, options, daily_factory=factory)
    bands: dict[str, tuple[float, float, str]] = {}
    for label, projection in raw.items():
        days = projection.days_analyzed
        if days >= 14:
            confidence = "high"
        elif days >= 7:
            confidence = "medium"
        else:
            confidence = "low"
        bands[label] = (
            max(0.0, projection.linear_low),
            projection.linear_high,
            confidence,
        )
    return bands


# ---------------------------------------------------------------------------
# Tier-source provenance — P11 power-up
# ---------------------------------------------------------------------------


_TIER_SOURCE_LABELS = {
    "cli": "CLI override",
    "json_override": "JSON override",
    "logged": "Logged in event",
    "codex_config": "Codex config",
    "assumed": "Assumed default",
}


def _build_tier_provenance(result: LoadResult) -> TierProvenance | None:
    raw = dict(result.tier_sources or {})
    total = sum(raw.values())
    if total <= 0:
        return None
    items = sorted(raw.items(), key=lambda kv: (-kv[1], kv[0]))
    labelled = tuple(
        (_TIER_SOURCE_LABELS.get(key, key.replace("_", " ").title()), count) for key, count in items
    )
    return TierProvenance(sources=labelled, total_events=total)


def _build_quality_score(
    result: LoadResult,
    total: Aggregate,
    evidence: list[EvidenceRow],
) -> QualityScore:
    if total.totals.events == 0:
        return QualityScore(
            score=0,
            grade="No evidence yet",
            signals=[
                QualitySignal(
                    label="Selected window",
                    status="unsupported",
                    note="No usage events were loaded; run `caliper doctor` or try demo data.",
                    tone="neutral",
                )
            ],
            tone="neutral",
        )
    status_scores = {"exact": 100, "estimated": 78, "partial": 55, "unsupported": 30}
    tone_by_status = {
        "exact": "good",
        "estimated": "neutral",
        "partial": "warn",
        "unsupported": "critical",
    }
    scores = [status_scores.get(row.status, 60) for row in evidence] or [75]
    score = sum(scores) / len(scores)

    penalty = 0
    parser_issue_count = sum(issue.count for issue in result.parser_issues)
    if parser_issue_count:
        penalty += min(18, parser_issue_count * 2)
    if result.warnings:
        penalty += min(10, len(result.warnings) * 2)
    if total.costs.unpriced_events:
        penalty += min(20, total.costs.unpriced_events * 3)
    if total.unknown_model_events:
        penalty += min(15, total.unknown_model_events * 2)
    if total.unknown_tier_events:
        penalty += min(12, total.unknown_tier_events)
    score = max(0, min(100, round(score - penalty)))
    if score >= 90:
        grade = "Excellent"
        tone = "good"
    elif score >= 75:
        grade = "Good"
        tone = "neutral"
    elif score >= 55:
        grade = "Needs review"
        tone = "warn"
    else:
        grade = "Weak"
        tone = "critical"

    signals = [
        QualitySignal(
            label=row.label,
            status=row.status,
            note=row.note,
            tone=tone_by_status.get(row.status, "neutral"),  # type: ignore[arg-type]
        )
        for row in evidence[:6]
    ]
    if parser_issue_count or result.warnings:
        signals.append(
            QualitySignal(
                label="Parser health",
                status="warn" if parser_issue_count or result.warnings else "exact",
                note=f"{parser_issue_count:,} parser issues · {len(result.warnings):,} warnings",
                tone="warn" if parser_issue_count or result.warnings else "good",
            )
        )
    if total.costs.unpriced_events or total.costs.estimated_events:
        signals.append(
            QualitySignal(
                label="Pricing coverage",
                status="partial" if total.costs.unpriced_events else "estimated",
                note=(
                    f"{total.costs.unpriced_events:,} unpriced events · "
                    f"{total.costs.estimated_events:,} estimated events"
                ),
                tone="critical" if total.costs.unpriced_events else "warn",
            )
        )
    if total.unknown_model_events or total.unknown_tier_events:
        signals.append(
            QualitySignal(
                label="Attribution gaps",
                status="partial",
                note=(
                    f"{total.unknown_model_events:,} unknown model · "
                    f"{total.unknown_tier_events:,} unknown tier"
                ),
                tone="warn",
            )
        )
    return QualityScore(score=score, grade=grade, signals=signals, tone=tone)  # type: ignore[arg-type]


def _build_comparisons(
    *,
    totals: Totals,
    usage_windows: list[UsageWindow],
    by_project: list[ProjectRow],
    by_model: list[ModelRow],
    top_sessions: list[SessionRow],
    rate_limit_pressure: RateLimitPressure,
    quality_score: QualityScore,
) -> list[ComparisonSignal]:
    windows = {window.days: window for window in usage_windows}
    out: list[ComparisonSignal] = []

    seven = windows.get(7)
    thirty = windows.get(30)
    ninety = windows.get(90)
    if seven and thirty and thirty.cost_usd > 0:
        seven_daily = seven.cost_usd / seven.days
        thirty_daily = thirty.cost_usd / thirty.days
        delta = (seven_daily - thirty_daily) / thirty_daily
        out.append(
            ComparisonSignal(
                label="7d spend velocity",
                value=f"{_format_money(seven_daily)}/day",
                detail=f"30d baseline {_format_money(thirty_daily)}/day",
                delta_pct=delta,
                tone=_delta_tone(delta, high_bad=True),
                anchor="usage-windows",
                lens="finance",
            )
        )
    if thirty and ninety and ninety.cost_usd > 0:
        thirty_daily = thirty.cost_usd / thirty.days
        ninety_daily = ninety.cost_usd / ninety.days
        delta = (thirty_daily - ninety_daily) / ninety_daily
        out.append(
            ComparisonSignal(
                label="30d baseline",
                value=f"{_format_money(thirty_daily)}/day",
                detail=f"90d baseline {_format_money(ninety_daily)}/day",
                delta_pct=delta,
                tone=_delta_tone(delta, high_bad=True),
                anchor="usage-windows",
                lens="executive",
            )
        )

    delta_specs = (
        (
            "Previous cost",
            totals.delta_cost_pct,
            "Cost vs previous equal window",
            "cost-over-time",
            True,
        ),
        (
            "Previous tokens",
            totals.delta_tokens_pct,
            "Tokens vs previous equal window",
            "usage-mix",
            True,
        ),
        (
            "Previous sessions",
            totals.delta_sessions_pct,
            "Sessions vs previous equal window",
            "top-sessions",
            True,
        ),
        (
            "Cache movement",
            totals.delta_cache_pct,
            "Cached-input share vs previous equal window",
            "usage-mix",
            False,
        ),
    )
    for label, delta, detail, anchor, high_bad in delta_specs:
        if delta is None:
            continue
        out.append(
            ComparisonSignal(
                label=label,
                value=_format_signed_pct(delta),
                detail=detail,
                delta_pct=delta,
                tone=_delta_tone(delta, high_bad=high_bad),
                anchor=anchor,
                lens="engineer" if label == "Cache movement" else "executive",
            )
        )

    total_cost = totals.cost_usd
    if total_cost > 0 and by_project:
        top = max(by_project, key=lambda row: row.cost_usd)
        share = top.cost_usd / total_cost
        out.append(
            ComparisonSignal(
                label="Top project concentration",
                value=_format_pct_round(share),
                detail=f"{top.name} is {_format_money(top.cost_usd)} of selected-window cost",
                delta_pct=None,
                tone="warn" if share >= 0.5 else "neutral",
                anchor="projects",
                lens="finance",
            )
        )
    if total_cost > 0 and by_model:
        top_model = max(by_model, key=lambda row: row.cost_usd)
        share = top_model.cost_usd / total_cost
        out.append(
            ComparisonSignal(
                label="Top model concentration",
                value=_format_pct_round(share),
                detail=(
                    f"{_humanize_model(top_model.model)} is "
                    f"{_format_money(top_model.cost_usd)} of selected-window cost"
                ),
                delta_pct=None,
                tone="warn" if share >= 0.5 else "neutral",
                anchor="models",
                lens="engineer",
            )
        )
    if total_cost > 0 and top_sessions:
        top_session = top_sessions[0]
        share = top_session.cost_usd / total_cost
        out.append(
            ComparisonSignal(
                label="Highest session share",
                value=_format_pct_round(share),
                detail=f"{_format_money(top_session.cost_usd)} · {top_session.reason}",
                delta_pct=None,
                tone="warn" if share >= 0.10 else "neutral",
                anchor="top-sessions",
                lens="engineer",
            )
        )

    peak_limit = max(
        [
            value
            for value in (
                rate_limit_pressure.peak_primary_pct,
                rate_limit_pressure.peak_secondary_pct,
            )
            if value is not None
        ],
        default=None,
    )
    out.append(
        ComparisonSignal(
            label="Rate-limit signal",
            value=_format_pct_round(peak_limit) if peak_limit is not None else "Unknown",
            detail=(
                f"{rate_limit_pressure.sample_count:,} samples"
                if rate_limit_pressure.sample_count
                else "No rate-limit samples recorded"
            ),
            delta_pct=None,
            tone=rate_limit_pressure.tone if peak_limit is not None else "neutral",
            anchor="rate-limits",
            lens="audit",
        )
    )
    out.append(
        ComparisonSignal(
            label="Evidence quality",
            value=f"{quality_score.score}/100",
            detail=quality_score.grade,
            delta_pct=None,
            tone=quality_score.tone,
            anchor="evidence",
            lens="audit",
        )
    )
    return out


def _build_decision_queue(
    *,
    total: Aggregate,
    impact_cards: list[ImpactCard],
    advisor_recommendations: list[AdvisorRecommendation],
    inefficiencies: list[InefficiencyRow],
    anomalies: list[AnomalyRow],
    top_sessions: list[SessionRow],
    by_project: list[ProjectRow],
    by_model: list[ModelRow],
    rate_limit_pressure: RateLimitPressure,
    quality_score: QualityScore,
    comparisons: list[ComparisonSignal],
) -> list[DecisionQueueItem]:
    total_cost = float(total.costs.cost_usd)
    raw: list[DecisionQueueItem] = []

    def add(
        title: str,
        detail: str,
        action: str,
        evidence: str,
        *,
        tone: str = "neutral",
        anchor: str = "",
        lens: str = "all",
    ) -> None:
        if title in {item.title for item in raw}:
            return
        raw.append(
            DecisionQueueItem(
                rank=0,
                title=title,
                detail=detail,
                action=action,
                evidence=evidence,
                tone=tone,  # type: ignore[arg-type]
                anchor=anchor,
                lens=lens,  # type: ignore[arg-type]
            )
        )

    if not total.totals.events:
        add(
            "Connect usage data",
            "No deduped usage events landed in the selected dashboard window.",
            "Run caliper doctor and verify vendor log locations.",
            "0 events in selected window",
            tone="warn",
            anchor="metric-glossary",
            lens="executive",
        )
        add(
            "Explore demo data",
            "Use Caliper's built-in sample data to inspect the dashboard before local logs exist.",
            "Run caliper dashboard --demo --open.",
            "0 events in selected window",
            tone="neutral",
            anchor="overview",
            lens="executive",
        )

    budget = next((card for card in impact_cards if card.label == "Budget risk"), None)
    if budget and budget.tone in {"critical", "warn"}:
        add(
            "Review budget posture",
            budget.detail,
            "Open Budget burn and decide whether the configured budget needs action.",
            budget.value,
            tone=budget.tone,
            anchor="budgets",
            lens="finance",
        )

    velocity = next((item for item in comparisons if item.label == "7d spend velocity"), None)
    if velocity and velocity.tone in {"critical", "warn"}:
        add(
            "Spend velocity changed",
            velocity.detail,
            "Review rolling windows and daily cost to find the date that moved the trend.",
            velocity.value,
            tone=velocity.tone,
            anchor=velocity.anchor,
            lens="executive",
        )

    if total_cost > 0 and by_project:
        top_project = max(by_project, key=lambda row: row.cost_usd)
        share = top_project.cost_usd / total_cost
        if share >= 0.45:
            add(
                "Project concentration is high",
                (
                    f"{top_project.name} accounts for {_format_pct_round(share)} "
                    "of selected-window cost."
                ),
                "Check the Projects table before treating the spend trend as broad usage.",
                f"{_format_money(top_project.cost_usd)} in {top_project.events:,} events",
                tone="warn",
                anchor="projects",
                lens="finance",
            )

    if total_cost > 0 and by_model:
        top_model = max(by_model, key=lambda row: row.cost_usd)
        share = top_model.cost_usd / total_cost
        if share >= 0.45:
            add(
                "Model concentration is high",
                (
                    f"{_humanize_model(top_model.model)} accounts for "
                    f"{_format_pct_round(share)} of selected-window cost."
                ),
                "Inspect model/tier mix before changing routing or budgets.",
                f"{_format_money(top_model.cost_usd)} across {top_model.events:,} events",
                tone="warn",
                anchor="models",
                lens="engineer",
            )

    savings = max((row.savings_usd for row in advisor_recommendations), default=0.0)
    if savings > 0:
        add(
            "Review avoidable spend",
            f"Largest advisor recommendation is {_format_money(savings)} at API rates.",
            ("Open Avoidable spend, then validate quality and latency before changing routing."),
            f"{len(advisor_recommendations):,} recommendations",
            tone="good",
            anchor="inefficiencies",
            lens="executive",
        )

    if inefficiencies:
        top_finding = max(inefficiencies, key=lambda row: row.impact_usd)
        add(
            "Review avoidable-spend finding",
            top_finding.detail,
            top_finding.action,
            f"{_format_money(top_finding.impact_usd)} · {top_finding.evidence_status}",
            tone="warn" if top_finding.severity in {"warn", "fail"} else "neutral",
            anchor="inefficiencies",
            lens="executive",
        )

    if anomalies:
        top_anomaly = anomalies[0]
        add(
            "Review anomaly finding",
            (
                f"{top_anomaly.kind} on {top_anomaly.label}: "
                f"observed {_format_money(top_anomaly.observed_usd)}."
            ),
            "Inspect the Anomalies section before treating the spike as a repeatable trend.",
            f"{top_anomaly.z_score:.1f}σ · {_format_money(top_anomaly.impact_usd)} impact",
            tone=top_anomaly.tone,
            anchor="anomalies",
            lens="audit",
        )

    if total_cost > 0 and top_sessions:
        top_session = top_sessions[0]
        share = top_session.cost_usd / total_cost
        add(
            "Inspect the highest-cost session",
            f"The top session is {_format_money(top_session.cost_usd)} and {top_session.reason}.",
            "Open the session table and inspect tokens, tools, models, and project attribution.",
            f"{_format_pct_round(share)} of selected-window cost",
            tone="warn" if share >= 0.10 else "neutral",
            anchor="top-sessions",
            lens="engineer",
        )

    if rate_limit_pressure.tone in {"critical", "warn"}:
        add(
            "Check rate-limit pressure",
            "Recorded limit samples show elevated usage pressure.",
            "Review latest primary and secondary pressure before planning another heavy session.",
            f"{rate_limit_pressure.sample_count:,} samples",
            tone=rate_limit_pressure.tone,
            anchor="rate-limits",
            lens="audit",
        )

    if quality_score.score < 75:
        add(
            "Review data quality",
            f"Evidence quality is {quality_score.score}/100 ({quality_score.grade}).",
            "Check pricing, parser, and attribution notes before acting on reported dollar values.",
            quality_score.grade,
            tone=quality_score.tone,
            anchor="evidence",
            lens="audit",
        )

    if not raw:
        add(
            "Keep monitoring",
            "No urgent cost, usage, reliability, or evidence issues stand out in this window.",
            "Use the rolling windows and forecast as the next periodic check.",
            f"{total.totals.events:,} deduped events",
            tone="good",
            anchor="command-center",
            lens="executive",
        )

    ordered = sorted(
        raw,
        key=lambda item: (_tone_rank(item.tone), item.lens != "executive", item.title),
    )[:5]
    return [dataclasses.replace(item, rank=index) for index, item in enumerate(ordered, start=1)]


def _build_executive_brief(
    *,
    totals: Totals,
    usage_windows: list[UsageWindow],
    decision_queue: list[DecisionQueueItem],
    comparisons: list[ComparisonSignal],
) -> ExecutiveBrief:
    if totals.events == 0:
        return ExecutiveBrief(
            title="No AI usage detected",
            verdict="Setup or date range needs review",
            subtitle=(
                "The selected window has no deduped usage events, so dashboard analysis is limited."
            ),
            tone="warn",
            findings=[
                BriefFinding(
                    title="Verify data sources",
                    detail=(
                        "Run caliper doctor and confirm that vendor logs exist for this date range."
                    ),
                    impact="No reportable usage",
                    tone="warn",
                    anchor="metric-glossary",
                    lens="executive",
                )
            ],
        )

    top_tone = min((item.tone for item in decision_queue), key=_tone_rank, default="neutral")
    warn_count = sum(1 for item in decision_queue if item.tone in {"critical", "warn"})
    good_count = sum(1 for item in decision_queue if item.tone == "good")
    # Keep the subtitle to a single scope (the selected window). The 7-day
    # velocity is its own decision-queue item, so blending it in here read as a
    # contradiction ("$1,243 … Last 7 days $799").
    subtitle = (
        f"{_format_money(totals.cost_usd)} selected-window cost · "
        f"{totals.events:,} deduped events · {totals.sessions:,} sessions"
    )
    if warn_count:
        title = "AI usage needs review"
        verdict = (
            f"{warn_count} item{'s' if warn_count != 1 else ''} to review "
            "before sharing or acting on this report."
        )
    elif good_count:
        title = "No warning-level issue surfaced"
        verdict = "Review avoidable-spend candidates when convenient."
    else:
        title = "No priority issue surfaced"
        verdict = "No generated cost, reliability, or evidence issue needs immediate action."

    findings = [
        BriefFinding(
            title=item.title,
            detail=item.detail,
            impact=item.evidence,
            tone=item.tone,
            anchor=item.anchor,
            lens=item.lens,
        )
        for item in decision_queue[:5]
    ]
    if not findings:
        findings = [
            BriefFinding(
                title="Stable report",
                detail="No cost, reliability, or evidence issue crossed an action threshold.",
                impact=f"{len(comparisons):,} comparisons checked",
                tone="good",
                anchor="action-center",
                lens="executive",
            )
        ]
    return ExecutiveBrief(
        title=title, verdict=verdict, subtitle=subtitle, tone=top_tone, findings=findings
    )  # type: ignore[arg-type]


def _delta_tone(delta: float | None, *, high_bad: bool) -> str:
    if delta is None:
        return "neutral"
    if high_bad:
        if delta >= 0.25:
            return "warn"
        if delta <= -0.15:
            return "good"
    else:
        if delta <= -0.10:
            return "warn"
        if delta >= 0.10:
            return "good"
    return "neutral"


def _tone_rank(tone: str) -> int:
    return {"critical": 0, "warn": 1, "good": 2, "neutral": 3}.get(tone, 3)


def _format_signed_pct(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.1f}%"


def _percent_fraction(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number / 100 if number > 1 else number


def _stringify_reset(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC).isoformat(timespec="minutes")
    return str(value)


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


_EVIDENCE_LABELS = {
    "usage": "Usage completeness",
    "model": "Model attribution",
    "tier": "Service tier",
    "pricing": "Pricing freshness",
    "project": "Project attribution",
    "git": "Git attribution",
}


def _build_evidence(result: LoadResult, total: Aggregate) -> list[EvidenceRow]:
    dims = evidence_dimensions(result, total)
    rows: list[EvidenceRow] = []
    for dim in dims:
        label = _EVIDENCE_LABELS.get(dim.name, dim.name.replace("_", " ").title())
        note = "; ".join(dim.reasons) if dim.reasons else ""
        rows.append(
            EvidenceRow(
                label=label,
                status=dim.grade,  # type: ignore[arg-type]
                note=note,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Banner detection
# ---------------------------------------------------------------------------


def _build_banner(result: LoadResult, options: RuntimeOptions) -> Banner | None:
    """Return at most one banner. Critical beats warning."""
    age = rate_card_age_days()
    if age > 90:
        return Banner(
            kind="crit",
            label="STALE",
            text=(
                f"Pricing data is {age} days old. Costs are extrapolated "
                "from the last known rate card. Run "
                "<code>caliper rates refresh --allow-network</code> for "
                "the latest."
            ),
        )
    vendors_active = {event.vendor for event in result.events if event.vendor}
    if len(vendors_active) == 1 and result.events:
        # Only one of the known vendors wrote logs in this window.
        return Banner(
            kind="warn",
            label="PARTIAL",
            text=(
                f"Showing {len(vendors_active)} of {KNOWN_VENDOR_COUNT} vendors. "
                "The others did not write parseable logs in this window. "
                "Run <code>caliper doctor</code> to verify your local "
                "setup."
            ),
        )
    if age > 30:
        return Banner(
            kind="warn",
            label="STALE",
            text=(
                f"Pricing data is {age} days old. Run "
                "<code>caliper rates refresh --allow-network</code> for "
                "the latest catalog."
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Yearly activity heatmap (GitHub-style 53×7 contribution grid)
# ---------------------------------------------------------------------------

# Pride and Prejudice is roughly 120k words → ~160k tokens at OpenAI's
# rough heuristic of 0.75 words per token (varies by tokenizer). Used in
# the Recap "you used Xx more tokens than …" line.
_PRIDE_AND_PREJUDICE_TOKENS = 160_000

# Calendar month names we surface in the heatmap footer.
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


# ---------------------------------------------------------------------------
# Recap card — hour-of-week heatmap + 2x4 stat grid + comparison
# ---------------------------------------------------------------------------


def _format_hour_12(hour: int) -> str:
    """0..23 → '12 AM' / '1 AM' / ... / '11 PM'."""
    if hour == 0:
        return "12 AM"
    if hour == 12:
        return "12 PM"
    if hour < 12:
        return f"{hour} AM"
    return f"{hour - 12} PM"


def _format_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def _humanize_model(model: str) -> str:
    """`claude-sonnet-4-6-20260501` → `Sonnet 4.6`. Best-effort."""
    import re

    if not model:
        return "—"
    m = re.match(r"claude-(\w+)-(\d+)-(\d+)", model)
    if m:
        name = m.group(1).capitalize()
        return f"{name} {m.group(2)}.{m.group(3)}"
    m = re.match(r"gpt-(\d+)\.(\d+)", model)
    if m:
        return f"GPT-{m.group(1)}.{m.group(2)}"
    return model


__all__ = ["build_handoff_dashboard", "tool_category"]
