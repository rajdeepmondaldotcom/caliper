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

DASHBOARD_SCHEMA_VERSION = 3


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
class MetricContext:
    """Human-readable definition metadata for dashboard metrics."""

    label: str
    scope: str
    formula: str
    source: str
    caveat: str = ""
    status: EvidenceStatus | None = None


@dataclass(frozen=True)
class AdvisorAlternative:
    model: str
    vendor: str
    projected_cost_usd: float
    savings_usd: float
    events: int = 0


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
    alternatives: tuple[AdvisorAlternative, ...] = ()


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
    # Which provider / coding tool these samples came from. Optional for
    # backwards compatibility with the legacy aggregate pressure object;
    # the new per-source breakdown sets it ("openai-codex", "claude-code").
    source: str = ""
    # Human-readable display label for the source (e.g. "Codex", "Claude
    # Code"). The renderer prefers this over a raw vendor id.
    source_label: str = ""


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
    comparison_scope: str = ""
    baseline_sample_count: int = 0
    reason: str = ""
    impact_percent: float | None = None


# ---------------------------------------------------------------------------
# Insights, forecast, evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Insight:
    severity: Severity
    title: str
    detail: str
    impact: str | None = None  # right-side chip; e.g. "est. $612"
    # Lineage chip ("based on N events · M sessions · X tokens"). Keys that
    # the renderer recognises today: ``events``, ``sessions``, ``tokens``.
    # When empty (or none of those keys present) the renderer prints nothing,
    # so an insight that legitimately has no sample-size lineage stays clean.
    evidence_metrics: dict[str, object] = field(default_factory=dict)


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


# ---------------------------------------------------------------------------
# Activity heatmap — GitHub-style yearly contribution grid
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Recap card — hour-of-week heatmap + stat grid + comparison line
# ---------------------------------------------------------------------------


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
# Output summary — "what did this spend produce?" (the leverage question)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutputSummary:
    """What the window's AI spend produced, from local git + tool evidence.

    Honest by construction. Every figure comes from logs already on disk:

    - ``commits_touched`` counts distinct git commit SHAs that were checked
      out while AI events were recorded.
    - ``cost_per_commit_usd`` divides the cost of those git-linked events by
      that count. It is a rough unit cost, not a per-commit invoice.
    - ``linked_cost_pct`` is the share of window cost recorded inside a git
      repo at a known commit. Unlinked spend is exploration, planning, or work
      that never reached a commit. It is **not** automatically waste.
    - ``edit_share`` / ``diagnostic_share`` / ``exploration_share`` are the
      fractions of classified tool calls that edit files, run/inspect, or read.
      A high diagnostic share with few edits is the rough "spinning, not
      shipping" signal.
    """

    commits_touched: int
    cost_per_commit_usd: float
    linked_cost_usd: float
    linked_cost_pct: float  # 0..1
    edit_share: float  # 0..1 of classified tool calls
    diagnostic_share: float  # 0..1
    exploration_share: float  # 0..1
    classified_tool_calls: int
    has_git: bool
    caveat: str = ""
    # When True, ``commits_touched`` is the count of commits authored in the
    # window in the repos the sessions touched (read from local ``git log``),
    # and ``cost_per_commit_usd`` is total window spend divided by that count.
    # When False, both fall back to the git-SHA proxy (commits whose checkout
    # was recorded on a spend event), which only some sources log.
    commits_from_git: bool = False


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
    by_model: list[ModelRow]
    by_project: list[ProjectRow]
    anomalies: list[AnomalyRow]
    insights: list[Insight]
    evidence: list[EvidenceRow]

    # "What did this produce?" — the leverage view, built from local git +
    # tool evidence. Optional so legacy/lean payloads still build.
    output_summary: OutputSummary | None = None

    advisor_recommendations: list[AdvisorRecommendation] = field(default_factory=list)
    top_sessions: list[SessionRow] = field(default_factory=list)
    agents: list[AgentRow] = field(default_factory=list)
    skills: list[SkillRow] = field(default_factory=list)
    inefficiencies: list[InefficiencyRow] = field(default_factory=list)
    rate_limit_pressure: RateLimitPressure | None = None
    # Per-source breakdown (one entry per provider/coding tool). When present,
    # the renderer shows a panel per source instead of the legacy aggregate.
    rate_limit_pressures: list[RateLimitPressure] = field(default_factory=list)
    quality_score: QualityScore | None = None
    # Feeds the top verdict strip (the "items to review" triage). Built from
    # the comparison/decision pipeline; not rendered as its own section.
    executive_brief: ExecutiveBrief | None = None

    banner: Banner | None = None
    show_paths: bool = False

    tier_provenance: TierProvenance | None = None

    # API-equivalent caveat when usage runs under a flat subscription (e.g.
    # Codex on a ChatGPT plan), so the above-the-fold cost reads as usage value
    # rather than an invoice. Empty when usage is genuinely metered.
    cost_note: str = ""

    # Cache reuse by session + long-context histogram (Avoidable spend + Attribution).
    cache_leverage: list[CacheLeverageRow] = field(default_factory=list)
    long_context_histogram: LongContextHistogram | None = None

    # Cohort delta table (Attribution).
    cohort_deltas: list[CohortDeltaRow] = field(default_factory=list)

    # Budget burn rows (daily / weekly / monthly).
    budgets: list[BudgetRow] = field(default_factory=list)
