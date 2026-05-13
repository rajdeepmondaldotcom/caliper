from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
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


def project_name_from_path(value: str) -> str:
    if not value:
        return UNKNOWN_PROJECT
    return Path(value).name or value or UNKNOWN_PROJECT


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

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

    def __init__(
        self,
        input: object,
        cached_input: object,
        output: object,
        reasoning_output: object | None = None,
    ) -> None:
        object.__setattr__(self, "input", decimal_value(input))
        object.__setattr__(self, "cached_input", decimal_value(cached_input))
        object.__setattr__(self, "output", decimal_value(output))
        object.__setattr__(
            self,
            "reasoning_output",
            None if reasoning_output is None else decimal_value(reasoning_output),
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
    offline: bool
    compact: bool
    width: int | None
    top_threads: int


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
    credits: object = None
    primary_used_percent: object = None
    primary_window_minutes: object = None
    primary_resets_at: object = None
    secondary_used_percent: object = None
    secondary_window_minutes: object = None
    secondary_resets_at: object = None
    rate_limit_reached_type: str = ""
    vendor: str = VENDOR_OPENAI_CODEX


@dataclass(frozen=True)
class RateLimitSample:
    timestamp: dt.datetime
    path: Path
    session_id: str
    plan_type: str = ""
    limit_id: str = ""
    limit_name: str = ""
    credits: object = None
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


@dataclass(init=False)
class CostTotals:
    api_dollars: Decimal
    standard_credits: Decimal
    adjusted_credits: Decimal
    api_unpriced_events: int
    credit_unpriced_events: int
    estimated_events: int
    ambiguous_reasoning_events: int
    local_override_events: int

    def __init__(
        self,
        api_dollars: object = Decimal("0"),
        standard_credits: object = Decimal("0"),
        adjusted_credits: object = Decimal("0"),
        api_unpriced_events: int = 0,
        credit_unpriced_events: int = 0,
        estimated_events: int = 0,
        ambiguous_reasoning_events: int = 0,
        local_override_events: int = 0,
    ) -> None:
        self.api_dollars = decimal_value(api_dollars)
        self.standard_credits = decimal_value(standard_credits)
        self.adjusted_credits = decimal_value(adjusted_credits)
        self.api_unpriced_events = api_unpriced_events
        self.credit_unpriced_events = credit_unpriced_events
        self.estimated_events = estimated_events
        self.ambiguous_reasoning_events = ambiguous_reasoning_events
        self.local_override_events = local_override_events

    @property
    def unpriced_events(self) -> int:
        return max(self.api_unpriced_events, self.credit_unpriced_events)

    def add(self, other: CostTotals) -> None:
        self.api_dollars += other.api_dollars
        self.standard_credits += other.standard_credits
        self.adjusted_credits += other.adjusted_credits
        self.api_unpriced_events += other.api_unpriced_events
        self.credit_unpriced_events += other.credit_unpriced_events
        self.estimated_events += other.estimated_events
        self.ambiguous_reasoning_events += other.ambiguous_reasoning_events
        self.local_override_events += other.local_override_events


@dataclass
class TokenTotals:
    events: int = 0
    input_tokens: int = 0
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
        self.cached_input_tokens += usage.cached_input_tokens
        self.output_tokens += usage.output_tokens
        self.reasoning_output_tokens += usage.reasoning_output_tokens
        self.total_tokens += usage.total_tokens


@dataclass
class ModelBreakdown:
    key: str
    model: str
    service_tier: str
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
        if event.model:
            self.models.add(event.model)
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
        breakdown_key = f"{event.model}\0{event.service_tier}"
        breakdown = self.model_breakdowns.setdefault(
            breakdown_key,
            ModelBreakdown(
                key=breakdown_key,
                model=event.model,
                service_tier=event.service_tier,
            ),
        )
        breakdown.add_event(event, costs, cache_savings, long_context, unknown_model, unknown_tier)


@dataclass(frozen=True)
class LoadResult:
    events: list[UsageEvent]
    duplicates: int
    tier_sources: dict[str, int]
    plan_types: set[str]
    credit_samples: list[RateLimitSample]
    warnings: list[str]
