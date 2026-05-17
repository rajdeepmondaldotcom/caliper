"""Adapter — map Caliper aggregator output to the handoff Dashboard shape.

The renderer (`caliper.dashboards.html`) consumes a `Dashboard` dataclass
defined in `data_models.py`. This adapter is the single bridge between our
existing `LoadResult` + `RuntimeOptions` + the existing aggregators /
insights / forecasts / evidence helpers and that contract.

Public entrypoint:

    build_handoff_dashboard(result, options, *, with_deltas=True) -> Dashboard

Everything below is internal and named `_build_*` for grep-ability.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any

from caliper.aggregation import (
    aggregate_daily,
    aggregate_model_mode,
    aggregate_projects,
    aggregate_total,
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
    category_label,
    compute_session_shape,
)
from caliper.dashboards.data_models import (
    Banner,
    CaliperMeta,
    CategoryCount,
    DailyPoint,
    Dashboard,
    EvidenceRow,
    Forecast,
    HeatCell,
    HourCell,
    Insight,
    ModelRow,
    ProjectRow,
    Recap,
    RecapStat,
    SessionShape,
    ToolCount,
    Totals,
    WindowMeta,
    YearlyHeatmap,
)
from caliper.evidence import evidence_dimensions
from caliper.forecasts import project as project_forecast
from caliper.health import rate_card_age_days
from caliper.insights import build_insights
from caliper.models import UNKNOWN_PROJECT, Aggregate, LoadResult, RuntimeOptions
from caliper.parser import load_usage
from caliper.pricing import load_rate_card, model_vendor

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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
_KNOWN_VENDOR_LABELS = ("Codex", "Claude Code", "Cursor", "Aider")


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
) -> Dashboard:
    """Assemble the handoff `Dashboard` payload for `render_dashboard`."""
    from caliper import __version__

    rate_card = load_rate_card(options)
    total = aggregate_total(result, options, rate_card=rate_card)
    daily_aggregates = aggregate_daily(result, options, rate_card=rate_card)
    shape_report = compute_session_shape(result)

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

    shape = _build_session_shape(shape_report)
    by_model = _build_model_rows(aggregate_model_mode(result, options, rate_card=rate_card))
    by_project = _build_project_rows(
        aggregate_projects(result, options, rate_card=rate_card),
        result,
        show_paths=options.show_paths,
    )
    insights = _build_insights(result, options, rate_card)
    forecast = _build_forecast(daily_points, options)
    evidence = _build_evidence(result, total)
    banner = _build_banner(result, options)
    heatmap = _build_yearly_heatmap(result, options)
    recap = _build_recap(result, options, total, by_model)

    return Dashboard(
        caliper=CaliperMeta(version=__version__, schema_version=2),
        window=_build_window(options, result),
        generated_at=(generated_at or dt.datetime.now(tz=dt.UTC)).isoformat(timespec="seconds"),
        totals=totals,
        daily=daily_points,
        shape=shape,
        by_model=by_model,
        by_project=by_project,
        insights=insights,
        forecast=forecast,
        evidence=evidence,
        heatmap=heatmap,
        recap=recap,
        banner=banner,
        show_paths=options.show_paths,
    )


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
    """True per-day cache hit rate, zero-filled across the window.

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
# Session shape (handoff version)
# ---------------------------------------------------------------------------


def _build_session_shape(report: SessionShapeReport) -> SessionShape:
    total = report.total_sessions or 1
    top_tools = [
        ToolCount(name=name, count=count, category=tool_category(name))  # type: ignore[arg-type]
        for name, count in report.tool_use.per_tool[:10]
    ]
    categories = [
        CategoryCount(
            category=_SHAPE_NAME_MAP.get(cat, "no-tools"),  # type: ignore[arg-type]
            label=category_label(cat),
            sessions=count,
            share=count / total,
        )
        for cat, count in report.category_counts
    ]
    return SessionShape(
        total_sessions=report.total_sessions,
        total_turns=report.total_turns,
        tool_use_total=report.tool_use.total_calls,
        tools_per_turn=report.tools_per_turn,
        coverage_events=report.coverage_events,
        coverage_total_events=report.coverage_total_events,
        top_tools=top_tools,
        categories=categories,
    )


# ---------------------------------------------------------------------------
# Model rows
# ---------------------------------------------------------------------------


def _build_model_rows(aggregates: list[Aggregate]) -> list[ModelRow]:
    rows: list[ModelRow] = []
    for agg in aggregates:
        if agg.totals.events == 0:
            continue
        model = next(iter(agg.models), "") or "unknown"
        tier = next(iter(agg.service_tiers), "") or "—"
        vendor = next(iter(agg.model_vendors), "") or model_vendor(model)
        input_tokens = agg.totals.input_tokens
        cache_hit_rate = agg.totals.cached_input_tokens / input_tokens if input_tokens else 0.0
        rows.append(
            ModelRow(
                vendor=vendor,
                model=model,
                tier=tier,
                cost_usd=float(agg.costs.cost_usd),
                events=agg.totals.events,
                tokens=agg.totals.total_tokens,
                cache_hit_rate=cache_hit_rate,
            )
        )
    return rows[:12]


# ---------------------------------------------------------------------------
# Project rows
# ---------------------------------------------------------------------------


def _build_project_rows(
    aggregates: list[Aggregate],
    result: LoadResult,
    *,
    show_paths: bool,
) -> list[ProjectRow]:
    """Map our project aggregates + per-project tool counters into rows.

    Project aggregates are keyed by full `cwd`. We derive per-project
    tool counts directly from the LoadResult events keyed by the same
    full path so two repos with the same basename never share a tool
    list.
    """
    from collections import Counter

    from caliper.models import project_name_from_path

    tools_by_path: dict[str, Counter[str]] = {}
    for event in result.events:
        if event.turn_facts is None:
            continue
        path = event.thread.cwd or ""
        bucket = tools_by_path.setdefault(path, Counter())
        for tool_name in event.turn_facts.tool_names:
            bucket[tool_name] += 1

    rows: list[ProjectRow] = []
    for agg in aggregates:
        if agg.totals.events == 0:
            continue
        path_str = agg.label
        name = project_name_from_path(path_str) if path_str else UNKNOWN_PROJECT
        top_tools_raw = tools_by_path.get(path_str, Counter()).most_common(3)
        top_tools = [
            ToolCount(name=tname, count=count, category=tool_category(tname))  # type: ignore[arg-type]
            for tname, count in top_tools_raw
        ]
        rows.append(
            ProjectRow(
                name=name,
                path=path_str if show_paths else None,
                cost_usd=float(agg.costs.cost_usd),
                events=agg.totals.events,
                sessions=len(agg.session_ids),
                top_tools=top_tools,
            )
        )
    return rows[:15]


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


def _build_insights(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: Any,
) -> list[Insight]:
    raw = build_insights(result, options, rate_card=rate_card)[:10]
    return [
        Insight(
            severity=_SEVERITY_MAP.get(item.severity, "info"),  # type: ignore[arg-type]
            title=item.title,
            detail=item.detail,
            impact=item.impact_label or None,
        )
        for item in raw
    ]


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


def _build_forecast(daily_points: list[DailyPoint], options: RuntimeOptions) -> Forecast | None:
    if not daily_points:
        return None
    values = [float(p.cost_usd) for p in daily_points]
    end = options.end.astimezone(dt.UTC)
    last_of_month = (end.replace(day=1) + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(
        days=1
    )
    days_remaining = max(0, (last_of_month.date() - end.date()).days)
    if days_remaining == 0:
        return None
    projection = project_forecast(values, days_remaining=days_remaining, unit="cost_usd")
    return Forecast(
        days_analyzed=projection.days_analyzed,
        days_remaining=projection.days_remaining,
        daily_mean=projection.daily_mean,
        daily_stdev=projection.daily_stdev,
        linear_total=projection.linear_total,
        linear_low=projection.linear_low,
        linear_high=projection.linear_high,
        ewma_total=projection.ewma_total,
    )


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


def _level_for(value: int, thresholds: tuple[int, int, int, int]) -> int:
    """5-bin heat level: 0 = empty, 1..4 = quartile bins of non-zero values."""
    if value <= 0:
        return 0
    t1, t2, t3, t4 = thresholds
    if value >= t4:
        return 4
    if value >= t3:
        return 3
    if value >= t2:
        return 2
    return 1


def _quartile_thresholds(values: list[int]) -> tuple[int, int, int, int]:
    """Four upper bin edges for non-zero values. Returns (t1, t2, t3, t4)."""
    non_zero = sorted(v for v in values if v > 0)
    if not non_zero:
        return (1, 1, 1, 1)
    n = len(non_zero)

    def pick(p: float) -> int:
        i = max(0, min(n - 1, int(p * (n - 1))))
        return non_zero[i]

    return (pick(0.20), pick(0.45), pick(0.70), pick(0.90))


def _streaks(values: list[int]) -> tuple[int, int]:
    """Return (longest_streak, current_streak) of consecutive active days.

    `values` is the daily series oldest→newest. A day is active if value > 0.
    """
    longest = 0
    run = 0
    for v in values:
        if v > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    # Current streak walks backward from the last day.
    current = 0
    for v in reversed(values):
        if v > 0:
            current += 1
        else:
            break
    return longest, current


def _build_yearly_heatmap(result: LoadResult, options: RuntimeOptions) -> YearlyHeatmap | None:
    """Compute a 365-day contribution grid ending at the window end.

    Metric: total tool calls per day (Claude Code only today; other vendors
    contribute 0 until their parsers learn tool-use extraction). Falls back
    to event count when no turn-facts data is present.
    """
    from collections import Counter

    from caliper.timeutil import load_timezone

    tz = load_timezone(options.timezone)
    end_day = options.end.astimezone(tz).date()
    start_day = end_day - dt.timedelta(days=364)  # 365 cells total

    daily_tool_calls: dict[str, int] = {}
    daily_events: dict[str, int] = {}
    for event in result.events:
        local_date = event.timestamp.astimezone(tz).date()
        if local_date < start_day or local_date > end_day:
            continue
        key = local_date.isoformat()
        daily_events[key] = daily_events.get(key, 0) + 1
        if event.turn_facts and event.turn_facts.tool_use_count:
            daily_tool_calls[key] = daily_tool_calls.get(key, 0) + event.turn_facts.tool_use_count

    using_tools = sum(daily_tool_calls.values()) > 0
    daily_series = daily_tool_calls if using_tools else daily_events
    metric_label = "AI tool calls" if using_tools else "AI events"

    if not daily_series and not result.events:
        return None

    # Build cells day-by-day.
    cells: list[HeatCell] = []
    day = start_day
    values_in_order: list[int] = []
    while day <= end_day:
        v = daily_series.get(day.isoformat(), 0)
        values_in_order.append(v)
        day = day + dt.timedelta(days=1)

    thresholds = _quartile_thresholds(values_in_order)
    day = start_day
    for v in values_in_order:
        cells.append(HeatCell(date=day.isoformat(), value=v, level=_level_for(v, thresholds)))
        day = day + dt.timedelta(days=1)

    total = sum(values_in_order)
    longest, current = _streaks(values_in_order)

    # Most active month — group cell totals by calendar month.
    month_totals: Counter[int] = Counter()
    for cell in cells:
        if cell.value <= 0:
            continue
        month_idx = int(cell.date[5:7])
        month_totals[month_idx] += cell.value
    most_active_month = "—"
    if month_totals:
        top_month_idx = max(month_totals.items(), key=lambda kv: kv[1])[0]
        most_active_month = _MONTH_NAMES[top_month_idx - 1]

    # Most active day — highest single-day value.
    most_active_day = "—"
    if total > 0:
        peak = max(cells, key=lambda c: c.value)
        peak_date = dt.date.fromisoformat(peak.date)
        most_active_day = peak_date.strftime("%b %d, %Y").replace(" 0", " ")

    return YearlyHeatmap(
        metric_label=metric_label,
        metric_total=total,
        cells=cells,
        most_active_month=most_active_month,
        most_active_day=most_active_day,
        longest_streak=longest,
        current_streak=current,
        legend_values=thresholds,
    )


# ---------------------------------------------------------------------------
# Recap card — hour-of-week heatmap + 2x4 stat grid + comparison
# ---------------------------------------------------------------------------


def _build_recap(
    result: LoadResult,
    options: RuntimeOptions,
    total: Aggregate,
    by_model: list[ModelRow],
) -> Recap | None:
    """Compute the recap card payload.

    Hour-of-week heat: 7 days × 24 hours, value = event count per cell.
    Stats: sessions, messages, total tokens, active days, current/longest
    streaks, peak hour, favourite model. Comparison: total tokens vs a
    well-known reference book.
    """
    from caliper.timeutil import load_timezone

    if not result.events:
        return None

    tz = load_timezone(options.timezone)
    hour_counts: dict[tuple[int, int], int] = {}
    active_days: set[str] = set()
    daily_event_counts: dict[str, int] = {}
    hour_of_day: dict[int, int] = {}
    for event in result.events:
        local = event.timestamp.astimezone(tz)
        dow = local.weekday()  # 0 = Monday
        hour = local.hour
        hour_counts[(dow, hour)] = hour_counts.get((dow, hour), 0) + 1
        hour_of_day[hour] = hour_of_day.get(hour, 0) + 1
        date_key = local.date().isoformat()
        active_days.add(date_key)
        daily_event_counts[date_key] = daily_event_counts.get(date_key, 0) + 1

    values = list(hour_counts.values())
    thresholds = _quartile_thresholds(values)
    hours: list[HourCell] = []
    for dow in range(7):
        for hour in range(24):
            v = hour_counts.get((dow, hour), 0)
            hours.append(
                HourCell(day_of_week=dow, hour=hour, value=v, level=_level_for(v, thresholds))
            )

    # Streaks across the contiguous daily series.
    start_day = options.start.astimezone(tz).date()
    end_day = options.end.astimezone(tz).date()
    streak_series: list[int] = []
    day = start_day
    while day < end_day:
        streak_series.append(daily_event_counts.get(day.isoformat(), 0))
        day = day + dt.timedelta(days=1)
    longest, current = _streaks(streak_series)

    # Peak hour
    peak_hour_label = "—"
    if hour_of_day:
        peak = max(hour_of_day.items(), key=lambda kv: kv[1])[0]
        peak_hour_label = _format_hour_12(peak)

    # Favorite model — by event count
    fav_model = "—"
    if by_model:
        top = max(by_model, key=lambda m: m.events)
        fav_model = _humanize_model(top.model)

    # Token comparison
    tokens = total.totals.total_tokens
    if tokens == 0:
        comparison = "No tokens to compare yet."
    else:
        ratio = tokens / _PRIDE_AND_PREJUDICE_TOKENS
        if ratio < 1:
            comparison = (
                f"You've used about {ratio * 100:.0f}% of the tokens in Pride and Prejudice."
            )
        else:
            comparison = f"You've used ~{ratio:.0f}× more tokens than Pride and Prejudice."

    stats = [
        RecapStat(label="Sessions", value=f"{len(total.session_ids):,}"),
        RecapStat(label="Events", value=f"{total.totals.events:,}"),
        RecapStat(label="Total tokens", value=_format_tokens(tokens)),
        RecapStat(label="Active days", value=str(len(active_days))),
        RecapStat(label="Current streak", value=f"{current}d"),
        RecapStat(label="Longest streak", value=f"{longest}d"),
        RecapStat(label="Peak hour", value=peak_hour_label),
        RecapStat(label="Favorite model", value=fav_model),
    ]

    return Recap(
        title="Caliper recap",
        stats=stats,
        hours=hours,
        comparison=comparison,
        legend_values=thresholds,
    )


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
