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


# ---------------------------------------------------------------------------
# Header / window
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaliperMeta:
    version: str  # e.g. "0.0.30"
    schema_version: int  # 2


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

    # 14-day sparklines. Lengths must match the daily series count.
    daily_cost_sparkline: list[float] = field(default_factory=list)
    daily_cache_sparkline: list[float] = field(default_factory=list)
    daily_token_sparkline: list[float] = field(default_factory=list)
    daily_session_sparkline: list[float] = field(default_factory=list)


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


@dataclass(frozen=True)
class ProjectRow:
    name: str  # basename
    path: str | None  # full path, shown only when --show-paths
    cost_usd: float
    events: int
    sessions: int
    top_tools: list[ToolCount]  # up to 3


# ---------------------------------------------------------------------------
# Insights, forecast, evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Insight:
    severity: Severity
    title: str
    detail: str
    impact: str | None = None  # right-side chip; e.g. "saves ~$612"


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
class EvidenceRow:
    label: str
    status: EvidenceStatus
    note: str  # may be ""


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
    insights: list[Insight]
    forecast: Forecast | None
    evidence: list[EvidenceRow]

    # New visual hero sections (yearly heatmap + recap card).
    # Optional so older fixtures continue to render.
    heatmap: YearlyHeatmap | None = None
    recap: Recap | None = None

    banner: Banner | None = None
    show_paths: bool = False
