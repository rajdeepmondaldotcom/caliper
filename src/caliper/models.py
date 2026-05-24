from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def decimal_value(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def decimal_string(value: object) -> str:
    amount = decimal_value(value)
    if amount == 0:
        return "0"
    return format(amount.normalize(), "f")


UNKNOWN_PROJECT = "Unknown Project"

VENDOR_OPENAI_CODEX = "openai-codex"
VENDOR_CLAUDE_CODE = "claude-code"
VENDOR_CURSOR = "cursor"
VENDOR_AIDER = "aider"
VENDOR_COPILOT = "copilot"
VENDOR_UNKNOWN = "unknown"

KNOWN_VENDORS = frozenset(
    {
        VENDOR_OPENAI_CODEX,
        VENDOR_CLAUDE_CODE,
        VENDOR_CURSOR,
        VENDOR_AIDER,
        VENDOR_COPILOT,
        VENDOR_UNKNOWN,
    }
)


@lru_cache(maxsize=8192)
def project_name_from_path(value: str) -> str:
    if not value:
        return UNKNOWN_PROJECT
    return Path(value).name or value or UNKNOWN_PROJECT


@dataclass(frozen=True, init=False)
class Usage:
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_1h_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int

    def __init__(
        self,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_output_tokens: int = 0,
        total_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int | None = None,
        cache_creation_input_1h_tokens: int = 0,
    ) -> None:
        object.__setattr__(self, "input_tokens", _safe_int(input_tokens))
        object.__setattr__(
            self,
            "cache_creation_input_tokens",
            _safe_int(cache_creation_input_tokens),
        )
        object.__setattr__(
            self,
            "cache_read_input_tokens",
            _safe_int(
                cached_input_tokens if cache_read_input_tokens is None else cache_read_input_tokens
            ),
        )
        object.__setattr__(
            self,
            "cache_creation_input_1h_tokens",
            _safe_int(cache_creation_input_1h_tokens),
        )
        object.__setattr__(self, "output_tokens", _safe_int(output_tokens))
        object.__setattr__(self, "reasoning_output_tokens", _safe_int(reasoning_output_tokens))
        object.__setattr__(self, "total_tokens", _safe_int(total_tokens))

    @property
    def cached_input_tokens(self) -> int:
        return (
            self.cache_creation_input_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_1h_tokens
        )

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    def is_zero(self) -> bool:
        return not (
            self.input_tokens
            or self.cached_input_tokens
            or self.output_tokens
            or self.reasoning_output_tokens
            or self.total_tokens
        )

    @classmethod
    def from_dict(cls, raw: object) -> Usage:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            input_tokens=_safe_int(raw.get("input_tokens")),
            cached_input_tokens=_safe_int(raw.get("cached_input_tokens")),
            cache_creation_input_tokens=_safe_int(raw.get("cache_creation_input_tokens")),
            cache_read_input_tokens=(
                _safe_int(raw.get("cache_read_input_tokens"))
                if "cache_read_input_tokens" in raw
                else None
            ),
            cache_creation_input_1h_tokens=_safe_int(raw.get("cache_creation_input_1h_tokens")),
            output_tokens=_safe_int(raw.get("output_tokens")),
            reasoning_output_tokens=_safe_int(raw.get("reasoning_output_tokens")),
            total_tokens=_safe_int(raw.get("total_tokens")),
        )


@dataclass(frozen=True, init=False)
class Rates:
    input: Decimal
    cached_input: Decimal
    output: Decimal
    reasoning_output: Decimal | None
    cache_creation_input: Decimal | None
    cache_creation_input_1h: Decimal | None

    def __init__(
        self,
        input: object,
        cached_input: object,
        output: object,
        reasoning_output: object | None = None,
        cache_creation_input: object | None = None,
        cache_creation_input_1h: object | None = None,
    ) -> None:
        object.__setattr__(self, "input", decimal_value(input))
        object.__setattr__(self, "cached_input", decimal_value(cached_input))
        object.__setattr__(self, "output", decimal_value(output))
        object.__setattr__(
            self,
            "reasoning_output",
            None if reasoning_output is None else decimal_value(reasoning_output),
        )
        object.__setattr__(
            self,
            "cache_creation_input",
            None if cache_creation_input is None else decimal_value(cache_creation_input),
        )
        object.__setattr__(
            self,
            "cache_creation_input_1h",
            None if cache_creation_input_1h is None else decimal_value(cache_creation_input_1h),
        )

    @property
    def effective_reasoning_output(self) -> Decimal:
        return self.reasoning_output if self.reasoning_output is not None else self.output


@dataclass(frozen=True)
class LongContextRule:
    threshold: int
    input_mult: float
    output_mult: float


@dataclass(frozen=True)
class PricingSource:
    name: str
    url: str
    checked: str


@dataclass(frozen=True)
class RuntimeOptions:
    session_root: Path
    state_db: Path
    config_path: Path
    start: dt.datetime
    end: dt.datetime
    timezone: str
    pricing_mode: str
    service_tier: str
    unknown_service_tier: str
    tier_overrides: Path | None
    rates_file: Path | None
    dedupe: bool
    parse_cache: bool
    default_model: str
    show_prompts: bool
    show_paths: bool
    offline: bool
    compact: bool
    width: int | None
    top_threads: int
    rate_limit_sample_limit: int = 100
    include_all_rate_limit_samples: bool = False
    pricing_source: str = "auto"
    pricing_cache_ttl_hours: int = 24
    order: str = "asc"
    start_of_week: str = "sunday"
    project: str | None = None
    instances: bool = False
    breakdown: bool = False
    cost_mode: str = "auto"
    vendors: tuple[str, ...] = ("all",)
    parse_workers: int = 1


@dataclass(frozen=True)
class ThreadMeta:
    rollout_path: str = ""
    title: str = ""
    first_user_message: str = ""
    cwd: str = ""
    git_branch: str = ""
    git_origin_url: str = ""
    git_sha: str = ""
    model: str = ""
    reasoning_effort: str = ""
    created_at: int = 0
    updated_at: int = 0
    source: str = ""
    model_provider: str = ""
    cli_version: str = ""
    agent_role: str = ""
    agent_nickname: str = ""
    memory_mode: str = ""
    thread_source: str = ""


@dataclass(frozen=True)
class TierOverride:
    service_tier: str
    session: str | None = None
    start: dt.datetime | None = None
    end: dt.datetime | None = None


@dataclass(frozen=True)
class TurnFacts:
    turn_index: int = 0
    parent_uuid: str = ""
    tool_use_count: int = 0
    tool_names: tuple[str, ...] = ()
    skill_names: tuple[str, ...] = ()
    has_thinking_block: bool = False

    @classmethod
    def from_dict(cls, raw: object) -> TurnFacts | None:
        if not isinstance(raw, dict):
            return None
        names = raw.get("tool_names")
        tool_names = tuple(str(item) for item in names) if isinstance(names, list | tuple) else ()
        skills = raw.get("skill_names")
        skill_names = (
            tuple(str(item) for item in skills) if isinstance(skills, list | tuple) else ()
        )
        return cls(
            turn_index=_safe_int(raw.get("turn_index")),
            parent_uuid=str(raw.get("parent_uuid") or ""),
            tool_use_count=_safe_int(raw.get("tool_use_count")),
            tool_names=tool_names,
            skill_names=skill_names,
            has_thinking_block=bool(raw.get("has_thinking_block")),
        )


@dataclass(frozen=True)
class UsageEvent:
    timestamp: dt.datetime
    path: Path
    session_id: str
    usage: Usage
    model: str
    service_tier: str
    tier_source: str
    thread: ThreadMeta
    model_source: str = ""
    model_is_fallback: bool = False
    usage_source: str = "last_token_usage"
    model_context_window: int = 0
    plan_type: str = ""
    limit_id: str = ""
    limit_name: str = ""
    primary_used_percent: object = None
    primary_window_minutes: object = None
    primary_resets_at: object = None
    secondary_used_percent: object = None
    secondary_window_minutes: object = None
    secondary_resets_at: object = None
    rate_limit_reached_type: str = ""
    vendor: str = VENDOR_OPENAI_CODEX
    vendor_reported_cost_usd: object = None
    source_line: int = 0
    event_id: str = ""
    message_id: str = ""
    request_id: str = ""
    dedupe_key: str = ""
    raw_model: str = ""
    turn_facts: TurnFacts | None = None


@dataclass(frozen=True)
class RateLimitSample:
    timestamp: dt.datetime
    path: Path
    session_id: str
    plan_type: str = ""
    limit_id: str = ""
    limit_name: str = ""
    primary_used_percent: object = None
    primary_window_minutes: object = None
    primary_resets_at: object = None
    secondary_used_percent: object = None
    secondary_window_minutes: object = None
    secondary_resets_at: object = None
    rate_limit_reached_type: str = ""
    vendor: str = VENDOR_OPENAI_CODEX


@dataclass(frozen=True)
class ParsedSessionRecord:
    event: UsageEvent | None = None
    counter_reset: bool = False
    sample: RateLimitSample | None = None


@dataclass(frozen=True)
class ParserIssue:
    vendor: str
    kind: str
    message: str
    severity: str = "warn"
    count: int = 1
    examples: tuple[str, ...] = ()

    def to_record(self) -> dict[str, object]:
        return {
            "vendor": self.vendor,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "count": self.count,
            "examples": list(self.examples),
        }


@dataclass(frozen=True)
class VendorParseStats:
    vendor: str
    discovered_files: int = 0
    files_with_events: int = 0
    unsupported_files: int = 0
    event_count: int = 0
    warning_count: int = 0

    def to_record(self) -> dict[str, object]:
        return {
            "vendor": self.vendor,
            "discovered_files": self.discovered_files,
            "files_with_events": self.files_with_events,
            "unsupported_files": self.unsupported_files,
            "event_count": self.event_count,
            "warning_count": self.warning_count,
        }


@dataclass(init=False)
class CostTotals:
    cost_usd: Decimal
    reported_cost_usd: Decimal
    calculated_cost_usd: Decimal
    reported_calculated_delta_usd: Decimal
    unpriced_events: int
    estimated_events: int
    ambiguous_reasoning_events: int
    local_override_events: int
    vendor_reported_events: int

    def __init__(
        self,
        cost_usd: object = Decimal("0"),
        reported_cost_usd: object = Decimal("0"),
        calculated_cost_usd: object | None = None,
        reported_calculated_delta_usd: object = Decimal("0"),
        unpriced_events: int = 0,
        estimated_events: int = 0,
        ambiguous_reasoning_events: int = 0,
        local_override_events: int = 0,
        vendor_reported_events: int = 0,
    ) -> None:
        self.cost_usd = decimal_value(cost_usd)
        self.reported_cost_usd = decimal_value(reported_cost_usd)
        self.calculated_cost_usd = (
            self.cost_usd if calculated_cost_usd is None else decimal_value(calculated_cost_usd)
        )
        self.reported_calculated_delta_usd = decimal_value(reported_calculated_delta_usd)
        self.unpriced_events = unpriced_events
        self.estimated_events = estimated_events
        self.ambiguous_reasoning_events = ambiguous_reasoning_events
        self.local_override_events = local_override_events
        self.vendor_reported_events = vendor_reported_events

    def add(self, other: CostTotals) -> None:
        self.cost_usd += other.cost_usd
        self.reported_cost_usd += other.reported_cost_usd
        self.calculated_cost_usd += other.calculated_cost_usd
        self.reported_calculated_delta_usd += other.reported_calculated_delta_usd
        self.unpriced_events += other.unpriced_events
        self.estimated_events += other.estimated_events
        self.ambiguous_reasoning_events += other.ambiguous_reasoning_events
        self.local_override_events += other.local_override_events
        self.vendor_reported_events += other.vendor_reported_events


@dataclass
class TokenTotals:
    events: int = 0
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_1h_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    def add_usage(self, usage: Usage) -> None:
        self.events += 1
        self.input_tokens += usage.input_tokens
        self.cache_creation_input_tokens += usage.cache_creation_input_tokens
        self.cache_read_input_tokens += usage.cache_read_input_tokens
        self.cache_creation_input_1h_tokens += usage.cache_creation_input_1h_tokens
        self.cached_input_tokens += usage.cached_input_tokens
        self.output_tokens += usage.output_tokens
        self.reasoning_output_tokens += usage.reasoning_output_tokens
        self.total_tokens += usage.total_tokens


@dataclass
class ModelBreakdown:
    key: str
    model: str
    service_tier: str
    model_vendor: str = "unknown"
    totals: TokenTotals = field(default_factory=TokenTotals)
    costs: CostTotals = field(default_factory=CostTotals)
    cache_savings: CostTotals = field(default_factory=CostTotals)
    plan_types: set[str] = field(default_factory=set)
    usage_sources: set[str] = field(default_factory=set)
    model_sources: set[str] = field(default_factory=set)
    long_context_events: int = 0
    unknown_model_events: int = 0
    unknown_tier_events: int = 0
    fallback_model_events: int = 0
    first_seen: dt.datetime | None = None
    last_seen: dt.datetime | None = None

    def add_event(
        self,
        event: UsageEvent,
        costs: CostTotals,
        cache_savings: CostTotals,
        long_context: bool,
        unknown_model: bool,
        unknown_tier: bool,
    ) -> None:
        self.totals.add_usage(event.usage)
        self.costs.add(costs)
        self.cache_savings.add(cache_savings)
        if event.plan_type:
            self.plan_types.add(event.plan_type)
        if event.usage_source:
            self.usage_sources.add(event.usage_source)
        if event.model_source:
            self.model_sources.add(event.model_source)
        self.long_context_events += int(long_context)
        self.unknown_model_events += int(unknown_model)
        self.unknown_tier_events += int(unknown_tier)
        self.fallback_model_events += int(event.model_is_fallback)
        if self.first_seen is None or event.timestamp < self.first_seen:
            self.first_seen = event.timestamp
        if self.last_seen is None or event.timestamp > self.last_seen:
            self.last_seen = event.timestamp


@dataclass
class Aggregate:
    key: str
    label: str
    totals: TokenTotals = field(default_factory=TokenTotals)
    costs: CostTotals = field(default_factory=CostTotals)
    cache_savings: CostTotals = field(default_factory=CostTotals)
    models: set[str] = field(default_factory=set)
    vendors: set[str] = field(default_factory=set)
    model_vendors: set[str] = field(default_factory=set)
    service_tiers: set[str] = field(default_factory=set)
    plan_types: set[str] = field(default_factory=set)
    usage_sources: set[str] = field(default_factory=set)
    model_sources: set[str] = field(default_factory=set)
    model_context_window: int = 0
    long_context_events: int = 0
    unknown_model_events: int = 0
    unknown_tier_events: int = 0
    fallback_model_events: int = 0
    model_breakdowns: dict[str, ModelBreakdown] = field(default_factory=dict)
    session_ids: set[str] = field(default_factory=set)
    project_paths: set[str] = field(default_factory=set)
    project_names: set[str] = field(default_factory=set)
    git_origins: set[str] = field(default_factory=set)
    git_branches: set[str] = field(default_factory=set)
    git_shas: set[str] = field(default_factory=set)
    agent_roles: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    first_seen: dt.datetime | None = None
    last_seen: dt.datetime | None = None

    def add_event(
        self,
        event: UsageEvent,
        costs: CostTotals,
        cache_savings: CostTotals,
        long_context: bool,
        unknown_model: bool,
        unknown_tier: bool,
    ) -> None:
        self._add_totals(event, costs, cache_savings)
        self._add_event_identity(event)
        self._add_project_identity(event)
        self._add_thread_metadata(event)
        self._touch_seen(event.timestamp)
        self._add_context_flags(event, long_context, unknown_model, unknown_tier)
        self._add_model_breakdown(
            event,
            costs,
            cache_savings,
            long_context,
            unknown_model,
            unknown_tier,
        )

    def _add_totals(
        self,
        event: UsageEvent,
        costs: CostTotals,
        cache_savings: CostTotals,
    ) -> None:
        self.totals.add_usage(event.usage)
        self.costs.add(costs)
        self.cache_savings.add(cache_savings)

    def _add_event_identity(self, event: UsageEvent) -> None:
        from caliper.taxonomy import model_vendor

        if event.model:
            self.models.add(event.model)
            self.model_vendors.add(model_vendor(event.model))
        if event.vendor:
            self.vendors.add(event.vendor)
        if event.service_tier:
            self.service_tiers.add(event.service_tier)
        if event.plan_type:
            self.plan_types.add(event.plan_type)
        if event.usage_source:
            self.usage_sources.add(event.usage_source)
        if event.model_source:
            self.model_sources.add(event.model_source)
        if event.session_id:
            self.session_ids.add(event.session_id)

    def _add_project_identity(self, event: UsageEvent) -> None:
        if event.thread.cwd:
            self.project_paths.add(event.thread.cwd)
            self.project_names.add(project_name_from_path(event.thread.cwd))
        else:
            self.project_names.add(UNKNOWN_PROJECT)

    def _add_thread_metadata(self, event: UsageEvent) -> None:
        if event.thread.git_origin_url:
            self.git_origins.add(event.thread.git_origin_url)
        if event.thread.git_branch:
            self.git_branches.add(event.thread.git_branch)
        if event.thread.git_sha:
            self.git_shas.add(event.thread.git_sha)
        if event.thread.agent_role:
            self.agent_roles.add(event.thread.agent_role)
        if event.thread.source:
            self.sources.add(event.thread.source)
        if event.thread.thread_source:
            self.sources.add(event.thread.thread_source)

    def _touch_seen(self, timestamp: dt.datetime) -> None:
        if self.first_seen is None or timestamp < self.first_seen:
            self.first_seen = timestamp
        if self.last_seen is None or timestamp > self.last_seen:
            self.last_seen = timestamp

    def _add_context_flags(
        self,
        event: UsageEvent,
        long_context: bool,
        unknown_model: bool,
        unknown_tier: bool,
    ) -> None:
        self.model_context_window = max(self.model_context_window, event.model_context_window)
        self.long_context_events += int(long_context)
        self.unknown_model_events += int(unknown_model)
        self.unknown_tier_events += int(unknown_tier)
        self.fallback_model_events += int(event.model_is_fallback)

    def _add_model_breakdown(
        self,
        event: UsageEvent,
        costs: CostTotals,
        cache_savings: CostTotals,
        long_context: bool,
        unknown_model: bool,
        unknown_tier: bool,
    ) -> None:
        from caliper.taxonomy import model_vendor

        breakdown_key = f"{event.model}\0{event.service_tier}"
        breakdown = self.model_breakdowns.setdefault(
            breakdown_key,
            ModelBreakdown(
                key=breakdown_key,
                model=event.model,
                service_tier=event.service_tier,
                model_vendor=model_vendor(event.model),
            ),
        )
        breakdown.add_event(event, costs, cache_savings, long_context, unknown_model, unknown_tier)


@dataclass(frozen=True)
class LoadResult:
    events: list[UsageEvent]
    duplicates: int
    tier_sources: dict[str, int]
    plan_types: set[str]
    rate_limit_samples: list[RateLimitSample]
    warnings: list[str]
    parser_issues: list[ParserIssue] = field(default_factory=list)
    vendor_stats: dict[str, VendorParseStats] = field(default_factory=dict)
    dedupe_stats: dict[str, int] = field(default_factory=dict)
    rate_limit_sample_duplicates: int = 0
    rate_limit_sample_dedupe_stats: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Predictive analytics + inefficiency detection value objects.
# Pure data — all numerics; no behaviour. Consumed by predict.py,
# anomaly.py, efficiency.py, and the dashboard adapter.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelDemandForecast:
    model: str
    model_vendor: str
    days_analyzed: int
    daily_mean_tokens: float
    daily_stdev_tokens: float
    trend_slope_tokens_per_day: float
    projected_share_30d: float
    growing: bool
    daily_mean_cost_usd: float
    projected_cost_30d_usd: float


@dataclass(frozen=True)
class SeasonalityProfile:
    by_hour_cost_usd: tuple[float, ...]
    by_dow_cost_usd: tuple[float, ...]
    peak_hour: int
    peak_dow: int
    off_peak_share: float
    timezone: str


@dataclass(frozen=True)
class RateLimitForecast:
    window: str
    limit_id: str
    limit_name: str
    current_percent: float | None
    burn_rate_per_hour: float | None
    eta_to_100_hours: float | None
    eta_low_hours: float | None
    eta_high_hours: float | None
    confidence: str
    samples: int


@dataclass(frozen=True)
class SessionShapeCluster:
    label: str
    sessions: int
    median_total_tokens: int
    median_cost_usd: Decimal
    p95_cost_usd: Decimal


@dataclass(frozen=True)
class Anomaly:
    kind: str
    timestamp: dt.datetime
    label: str
    observed: float
    baseline_center: float
    baseline_scale: float
    z_score: float
    impact_usd_exact: Decimal
    comparison_scope: str = ""
    baseline_sample_count: int = 0
    cohort_key: str = ""
    cohort_label: str = ""
    reason: str = ""
    dedupe_key: str = ""
    impact_percent: float | None = None


@dataclass(frozen=True)
class Finding:
    """A quantified inefficiency. ``impact_usd_exact`` is the dollar
    saving available if the suggested action is taken. Never ``None`` —
    finders that cannot quantify do not emit."""

    code: str
    severity: str
    title: str
    detail: str
    action: str
    payback_action: str
    scope: str
    impact_usd_exact: Decimal
    monthly_projected_savings_usd: Decimal
    confidence: str
    evidence: tuple[str, ...]
    evidence_metrics: dict[str, object] = field(default_factory=dict)
    commands: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    evidence_status: str = "estimated"
    sample_size: int = 0
    baseline: str = ""


@dataclass(frozen=True)
class Recommendation:
    """A composed, ranked, action-first piece of advice. Wraps a Finding
    or trend signal; the dashboard's advisor slot renders these directly."""

    rank: int
    title: str
    payback_action: str
    detail: str
    impact_usd_exact: Decimal
    monthly_projected_savings_usd: Decimal
    confidence: str
    source_code: str
    commands: tuple[str, ...] = ()
