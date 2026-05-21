"""
Caliper dashboard — data models.

Pure-stdlib dataclasses that mirror the TypeScript interfaces in the design
brief (07-DATA-SHAPES.md). The dashboard renderer (see `caliper_html.py`)
consumes a `Dashboard` instance and returns a single HTML string.

These shapes are the contract between the parser/aggregator and the renderer.
Don't add presentation-only fields here — keep this file numeric and parse-able.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Enums (string literals so JSON dumps are still inspectable)
# ---------------------------------------------------------------------------

ToolCategory = Literal["explore", "execute", "diagnose", "mixed"]
SessionShapeName = Literal["exploration", "execution", "diagnostic", "mixed", "no-tools"]
Severity = Literal["info", "warn", "critical"]
EvidenceStatus = Literal["exact", "estimated", "partial", "unsupported"]
ImpactTone = Literal["neutral", "good", "warn", "critical"]
DashboardLens = Literal["executive", "engineer", "finance", "audit"]


# ---------------------------------------------------------------------------
# Header / window
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaliperMeta:
    version: str  # e.g. "0.0.30"
    schema_version: int  # 3 (added seasonality/tier-provenance/rate-limit ETA bands)
    # Optional build SHA (short hex) — surfaced in the masthead build id
    # ``CALIPER-YYYYMMDD-XXXX``. Empty string is fine (shows ``0000``).
    build_sha: str = ""


@dataclass(frozen=True)
class WindowMeta:
    start: str  # ISO date, inclusive  ("2026-05-03")
    end: str  # ISO date, exclusive  ("2026-05-17")
    label: str  # "Last 14 days"
    range: str  # "2026-05-03 → 2026-05-17"  (display-formatted)
    timezone: str  # IANA, e.g. "America/Los_Angeles"
    vendors_active: list[str]
    vendor_count_total: int


# ---------------------------------------------------------------------------
# Totals (card values + sparklines)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Totals:
    cost_usd: float
    events: int
    cache_savings_usd: float
    cache_hit_rate: float  # 0..1
    total_tokens: int
    cached_input_tokens: int
    uncached_input_tokens: int
    output_tokens: int
    sessions: int
    turns: int
    tools_per_turn: float

    # Period-over-period deltas, 0..1 fractions.
    # None hides the chip; 0 prints a flat indicator.
    delta_cost_pct: float | None = None
    delta_cache_pct: float | None = None
    delta_tokens_pct: float | None = None
    delta_sessions_pct: float | None = None

    # Selected-window sparklines. Lengths must match the daily series count.
    daily_cost_sparkline: list[float] = field(default_factory=list)
    daily_cache_sparkline: list[float] = field(default_factory=list)
    daily_token_sparkline: list[float] = field(default_factory=list)
    daily_session_sparkline: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class UsageWindow:
    label: str  # "Last 7 days"
    days: int
    start: str  # ISO date, inclusive
    end: str  # ISO date, exclusive
    range: str
    cost_usd: float
    total_tokens: int
    events: int
    sessions: int
    cache_hit_rate: float
    active_days: int
    daily_cost_sparkline: list[float] = field(default_factory=list)
    daily_token_sparkline: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class ImpactCard:
    label: str
    value: str
    detail: str
    tone: ImpactTone = "neutral"


@dataclass(frozen=True)
class BudgetRow:
    """Single budget burn row for the budgets section.

    Surfaces an `evaluate_budgets()` result in the shape the renderer expects:
    a period label, the dollar amount spent so far, the budget cap, and the
    warning threshold (in dollars, not a fraction) — plus an explicit tone so
    the renderer doesn't have to re-derive it.
    """

    period: str  # "daily" | "weekly" | "monthly" (display-formatted)
    spent: float
    cap: float
    warn: float  # warning threshold in dollars (e.g. 80% of cap)
    tone: ImpactTone = "neutral"


@dataclass(frozen=True)
class CommandCenterCard:
    label: str
    value: str
    detail: str
    tone: ImpactTone = "neutral"
    metric: str = ""


@dataclass(frozen=True)
class MetricContext:
    """Human-readable definition metadata for dashboard metrics."""

    label: str
    scope: str
    formula: str
    source: str
    caveat: str = ""
    status: EvidenceStatus | None = None


@dataclass(frozen=True)
class AdvisorRecommendation:
    title: str
    value: str
    detail: str
    action: str
    confidence: float
    events: int
    sessions: int
    tone: ImpactTone = "neutral"
    savings_usd: float = 0.0


@dataclass(frozen=True)
class BriefFinding:
    title: str
    detail: str
    impact: str
    tone: ImpactTone = "neutral"
    anchor: str = ""
    lens: DashboardLens | Literal["all"] = "all"


@dataclass(frozen=True)
class ExecutiveBrief:
    title: str
    verdict: str
    subtitle: str
    tone: ImpactTone = "neutral"
    findings: list[BriefFinding] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionQueueItem:
    rank: int
    title: str
    detail: str
    action: str
    evidence: str
    tone: ImpactTone = "neutral"
    anchor: str = ""
    lens: DashboardLens | Literal["all"] = "all"


@dataclass(frozen=True)
class ComparisonSignal:
    label: str
    value: str
    detail: str
    tone: ImpactTone = "neutral"
    delta_pct: float | None = None
    anchor: str = ""
    lens: DashboardLens | Literal["all"] = "all"


@dataclass(frozen=True)
class SessionRow:
    label: str
    started_at: str
    project: str
    cost_usd: float
    total_tokens: int
    events: int
    tool_calls: int
    models: list[str]
    reason: str


@dataclass(frozen=True)
class MixRow:
    dimension: str
    label: str
    cost_usd: float
    total_tokens: int
    events: int
    share: float
    daily_cost_sparkline: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class AgentRow:
    agent_id: str
    source_category: str
    evidence_status: EvidenceStatus
    reason: str
    kind: str
    cost_usd: float
    total_tokens: int
    events: int
    tool_calls: int
    sessions: int
    daily_cost_sparkline: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class CohortDeltaRow:
    """Side-by-side delta between selected window and the prior equal window."""

    label: str
    current_value: str  # display-formatted
    previous_value: str
    delta_pct: float | None  # 0..n fraction; None when prior is zero
    delta_value: float  # signed absolute delta in the row's natural unit
    tone: ImpactTone = "neutral"


@dataclass(frozen=True)
class SkillRow:
    name: str
    evidence_status: EvidenceStatus
    attribution_method: str
    estimated_cost_usd: float
    median_cost_per_invocation_usd: float
    total_tokens: int
    invocations: int
    sessions: int


@dataclass(frozen=True)
class InefficiencyRow:
    code: str
    severity: str
    evidence_status: EvidenceStatus
    title: str
    detail: str
    action: str
    impact_usd: float
    monthly_projected_savings_usd: float
    confidence: str
    sample_size: int
    baseline: str
    # Phase 3: per-turn input-token curve for ``PROMPT_ROT`` rows
    # (median across flagged sessions). Empty for every other code.
    curve: tuple[int, ...] = ()


@dataclass(frozen=True)
class CacheLeverageRow:
    """One session's cache-leverage signature.

    ``savings_usd`` is the cost the cached input would have incurred at the
    uncached input rate. ``hit_rate`` = cached / (cached + uncached) input.
    """

    session_label: str
    project: str
    savings_usd: float
    hit_rate: float
    cached_input_tokens: int
    uncached_input_tokens: int


@dataclass(frozen=True)
class LongContextHistogram:
    """Distribution of per-event input tokens with the LC threshold marked.

    ``bins`` is the left edge of each fixed log-spaced bucket; ``counts`` is
    the matching event count. ``threshold_tokens`` is the per-model
    long-context threshold (e.g. 200k for Sonnet 4.6). The two share fields
    summarise how concentrated spend is above that line.
    """

    bins: tuple[int, ...]
    counts: tuple[int, ...]
    threshold_tokens: int
    share_above_threshold: float  # 0..1 of events crossing the LC line
    cost_share_above_threshold: float  # 0..1 of spend that crossed it
    total_events: int


@dataclass(frozen=True)
class ForecastDriverRow:
    dimension: str
    label: str
    evidence_status: EvidenceStatus
    projected_30d_cost_usd: float
    daily_mean_cost_usd: float
    share: float
    driver: str


@dataclass(frozen=True)
class RateLimitForecastBand:
    """Time-to-exhaustion projection for one rate-limit window.

    All hour values are ``None`` when the burn rate cannot be estimated
    (no upward pressure or too few samples). ``confidence`` is one of
    ``"low" | "medium" | "high"`` and depends on the sample count plus
    burn-rate stability over the lookback window.
    """

    window: str  # "primary" | "secondary"
    limit_name: str
    current_percent: float | None
    burn_rate_per_hour: float | None
    eta_low_hours: float | None
    eta_mid_hours: float | None
    eta_high_hours: float | None
    confidence: str  # "low" | "medium" | "high"
    samples: int


@dataclass(frozen=True)
class RateLimitPressure:
    sample_count: int
    peak_primary_pct: float | None
    peak_secondary_pct: float | None
    latest_primary_pct: float | None
    latest_secondary_pct: float | None
    latest_limit_name: str
    latest_plan_type: str
    latest_resets_at: str
    reached_count: int
    tone: ImpactTone = "neutral"
    forecasts: tuple[RateLimitForecastBand, ...] = ()


@dataclass(frozen=True)
class QualitySignal:
    label: str
    status: str
    note: str
    tone: ImpactTone = "neutral"


@dataclass(frozen=True)
class QualityScore:
    score: int
    grade: str
    signals: list[QualitySignal]
    tone: ImpactTone = "neutral"


# ---------------------------------------------------------------------------
# Daily bar chart + dominant-shape strip
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyPoint:
    day: str  # "2026-05-10"
    cost_usd: float
    events: int
    shape: SessionShapeName


# ---------------------------------------------------------------------------
# Session shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCount:
    name: str  # "Read"
    count: int
    category: ToolCategory


@dataclass(frozen=True)
class CategoryCount:
    category: SessionShapeName
    label: str  # "exploration · read-heavy"
    sessions: int
    share: float  # 0..1


@dataclass(frozen=True)
class SessionShape:
    total_sessions: int
    total_turns: int
    tool_use_total: int
    tools_per_turn: float
    coverage_events: int
    coverage_total_events: int
    top_tools: list[ToolCount]
    categories: list[CategoryCount]


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelRow:
    vendor: str  # "anthropic"
    model: str  # "claude-sonnet-4-6"
    tier: str  # "standard" | "fast"
    cost_usd: float
    events: int
    tokens: int
    cache_hit_rate: float
    daily_cost_sparkline: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectRow:
    name: str  # basename
    path: str | None  # full path, shown only when --show-paths
    cost_usd: float
    events: int
    sessions: int
    top_tools: list[ToolCount]  # up to 3
    active_days: int = 0
    last_seen: str = ""
    daily_mean_cost_usd: float = 0.0
    projected_30d_cost_usd: float = 0.0
    trend_label: str = ""
    trend_tone: ImpactTone = "neutral"
    daily_cost_sparkline: list[float] = field(default_factory=list)
    # Phase 2 — per-project forecast confidence band.
    # ``forecast_confidence`` is "low" | "medium" | "high" | "" when no
    # forecast is available (sparse history). The ``low`` / ``high`` USD
    # values are ``0.0`` when no band could be computed.
    projected_30d_low: float = 0.0
    projected_30d_high: float = 0.0
    forecast_confidence: str = ""


@dataclass(frozen=True)
class AnomalyRow:
    kind: str
    label: str
    timestamp: str
    observed_usd: float
    baseline_usd: float
    baseline_scale_usd: float
    z_score: float
    impact_usd: float
    evidence_status: EvidenceStatus
    tone: ImpactTone = "warn"


# ---------------------------------------------------------------------------
# Insights, forecast, evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Insight:
    severity: Severity
    title: str
    detail: str
    impact: str | None = None  # right-side chip; e.g. "est. $612"


@dataclass(frozen=True)
class Forecast:
    days_analyzed: int
    days_remaining: int
    daily_mean: float
    daily_stdev: float
    linear_total: float
    linear_low: float  # -1σ
    linear_high: float  # +1σ
    ewma_total: float


@dataclass(frozen=True)
class OutlookHorizon:
    """One horizon of the dual 30/90-day portfolio outlook."""

    days: int  # 30 or 90
    linear_total: float
    linear_low: float
    linear_high: float
    ewma_total: float


@dataclass(frozen=True)
class Outlook:
    """Stakeholder-grade 30/90-day spend outlooks side-by-side.

    Distinct from ``Forecast`` (single-horizon, days_remaining-bounded)
    — ``Outlook`` is forward-looking from "today" by 30 and 90 days.
    """

    days_analyzed: int
    daily_mean: float
    daily_stdev: float
    horizon_30d: OutlookHorizon
    horizon_90d: OutlookHorizon


@dataclass(frozen=True)
class ModelForecastRow:
    """One card in the per-model forecast strip (top N by cost)."""

    vendor: str
    model: str
    days_analyzed: int
    daily_mean_cost_usd: float
    projected_30d_cost_usd: float
    projected_30d_low: float
    projected_30d_high: float
    ewma_30d_cost_usd: float
    trend_label: str
    trend_tone: ImpactTone = "neutral"
    daily_cost_sparkline: list[float] = field(default_factory=list)
    growing: bool = False


@dataclass(frozen=True)
class EvidenceRow:
    label: str
    status: EvidenceStatus
    note: str  # may be ""


@dataclass(frozen=True)
class TierProvenance:
    """Where each event's service tier resolution came from.

    ``sources`` is a list of ``(source_label, event_count)`` tuples,
    sorted by count descending. ``total_events`` is the sum.
    Sources include ``cli``, ``json_override``, ``logged``, ``codex_config``,
    ``assumed`` — see ``parser._tier_sources_from_events``.
    """

    sources: tuple[tuple[str, int], ...]
    total_events: int


@dataclass(frozen=True)
class SeasonalitySection:
    """Cost-weighted hour-of-day + day-of-week distribution.

    Distinct from ``Recap.hours`` (event-count grid): values here are USD,
    computed via ``predict.decompose_seasonality``.
    """

    by_hour_cost_usd: tuple[float, ...]  # 24 entries, Mon..Sun summed
    by_dow_cost_usd: tuple[float, ...]  # 7 entries, Mon=0..Sun=6
    by_dow_hour_cost_usd: tuple[tuple[float, ...], ...]  # 7×24 matrix
    peak_hour: int  # 0..23
    peak_dow: int  # 0..6
    off_peak_share: float  # cost fraction in lower-spend half of hours
    timezone: str
    total_cost_usd: float


# ---------------------------------------------------------------------------
# Activity heatmap — GitHub-style yearly contribution grid
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeatCell:
    """One cell in the yearly heatmap. `level` is 0..4 (5 bins, 0 = empty)."""

    date: str  # ISO YYYY-MM-DD
    value: int
    level: int  # 0..4


@dataclass(frozen=True)
class YearlyHeatmap:
    metric_label: str  # "AI events" / "Tool calls" / "Tokens"
    metric_total: int  # total over the whole window (the big headline number)
    cells: list[HeatCell]  # 365 / 366 cells, oldest first, contiguous
    most_active_month: str  # "July" — full month name
    most_active_day: str  # "Feb 4, 2026" — short, display-formatted
    longest_streak: int  # consecutive active days
    current_streak: int  # consecutive active days ending today (or window end)
    legend_values: tuple[int, int, int, int]  # thresholds for levels 1..4 (inclusive)


# ---------------------------------------------------------------------------
# Recap card — hour-of-week heatmap + stat grid + comparison line
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HourCell:
    """One cell in the 7×24 hour-of-week heatmap. `level` is 0..4."""

    day_of_week: int  # 0 = Monday, 6 = Sunday
    hour: int  # 0..23, local-tz
    value: int
    level: int  # 0..4


@dataclass(frozen=True)
class RecapStat:
    label: str
    value: str  # display string (already formatted)


@dataclass(frozen=True)
class Recap:
    """Personal recap card — modelled after a year-in-review summary."""

    title: str  # e.g. "What's up next, Rajdeep?" or "Caliper recap"
    stats: list[RecapStat]  # exactly 8 stats in a 4x2 grid
    hours: list[HourCell]  # 168 cells (7×24), ordered by (day_of_week, hour)
    comparison: str  # e.g. "You've used ~39× more tokens than Pride and Prejudice."
    legend_values: tuple[int, int, int, int]  # thresholds for hour levels 1..4


# ---------------------------------------------------------------------------
# Banner — at most one rendered above the cards
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Banner:
    kind: Literal["warn", "crit"]  # warn = vendor coverage, crit = stale pricing
    label: str  # "PARTIAL" / "STALE"
    text: str  # body; can contain HTML for inline <code>


# ---------------------------------------------------------------------------
# Filter pills — purely visual, no interactivity (static HTML)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FilterPill:
    label: str
    active: bool


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Dashboard:
    caliper: CaliperMeta
    window: WindowMeta
    generated_at: str  # ISO 8601 with offset

    totals: Totals
    daily: list[DailyPoint]
    shape: SessionShape
    by_model: list[ModelRow]
    by_project: list[ProjectRow]
    anomalies: list[AnomalyRow]
    insights: list[Insight]
    forecast: Forecast | None
    evidence: list[EvidenceRow]

    # Rolling, overlapping usage windows. These are intentionally separate
    # from `totals`, which remains the selected report window.
    usage_windows: list[UsageWindow] = field(default_factory=list)
    impact_cards: list[ImpactCard] = field(default_factory=list)

    # Richer analysis report sections. The renderer treats these as optional
    # so lean/legacy dashboard payloads still work.
    command_center: list[CommandCenterCard] = field(default_factory=list)
    advisor_recommendations: list[AdvisorRecommendation] = field(default_factory=list)
    top_sessions: list[SessionRow] = field(default_factory=list)
    usage_mix: list[MixRow] = field(default_factory=list)
    agents: list[AgentRow] = field(default_factory=list)
    skills: list[SkillRow] = field(default_factory=list)
    inefficiencies: list[InefficiencyRow] = field(default_factory=list)
    forecast_drivers: list[ForecastDriverRow] = field(default_factory=list)
    rate_limit_pressure: RateLimitPressure | None = None
    quality_score: QualityScore | None = None
    executive_brief: ExecutiveBrief | None = None
    decision_queue: list[DecisionQueueItem] = field(default_factory=list)
    comparisons: list[ComparisonSignal] = field(default_factory=list)
    default_lens: DashboardLens = "executive"

    # New visual hero sections (yearly heatmap + recap card).
    # Optional so older fixtures continue to render.
    heatmap: YearlyHeatmap | None = None
    recap: Recap | None = None

    banner: Banner | None = None
    show_paths: bool = False

    # Phase 1 power-ups: cost-weighted seasonality + tier provenance.
    seasonality: SeasonalitySection | None = None
    tier_provenance: TierProvenance | None = None

    # Phase 2 power-ups: per-model forecast strip + portfolio 30/90d outlook.
    model_forecasts: list[ModelForecastRow] = field(default_factory=list)
    outlook: Outlook | None = None

    # Phase 3 power-ups: cache leverage by session + long-context histogram.
    cache_leverage: list[CacheLeverageRow] = field(default_factory=list)
    long_context_histogram: LongContextHistogram | None = None

    # Phase 4 power-ups: cohort delta table (compare lens) + agent sparklines.
    cohort_deltas: list[CohortDeltaRow] = field(default_factory=list)

    # v2 redesign: dedicated budget burn rows (daily / weekly / monthly).
    # Optional so older fixtures that omit this field still build.
    budgets: list[BudgetRow] = field(default_factory=list)
