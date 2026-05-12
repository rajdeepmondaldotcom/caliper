from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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


@dataclass(frozen=True)
class Rates:
    input: float
    cached_input: float
    output: float
    reasoning_output: float | None = None

    @property
    def effective_reasoning_output(self) -> float:
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
    default_model: str
    show_prompts: bool
    offline: bool
    compact: bool
    top_threads: int


@dataclass(frozen=True)
class ThreadMeta:
    rollout_path: str = ""
    title: str = ""
    first_user_message: str = ""
    cwd: str = ""
    git_branch: str = ""
    git_origin_url: str = ""
    model: str = ""
    reasoning_effort: str = ""
    created_at: int = 0
    updated_at: int = 0


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
    usage_source: str = "last_token_usage"
    model_context_window: int = 0
    plan_type: str = ""
    credits: object = None
    primary_used_percent: object = None
    primary_window_minutes: object = None
    primary_resets_at: object = None
    secondary_used_percent: object = None
    secondary_window_minutes: object = None
    secondary_resets_at: object = None
    rate_limit_reached_type: str = ""


@dataclass(frozen=True)
class RateLimitSample:
    timestamp: dt.datetime
    path: Path
    session_id: str
    plan_type: str = ""
    credits: object = None
    primary_used_percent: object = None
    primary_window_minutes: object = None
    primary_resets_at: object = None
    secondary_used_percent: object = None
    secondary_window_minutes: object = None
    secondary_resets_at: object = None
    rate_limit_reached_type: str = ""


@dataclass
class CostTotals:
    api_dollars: float = 0.0
    standard_credits: float = 0.0
    adjusted_credits: float = 0.0

    def add(self, other: CostTotals) -> None:
        self.api_dollars += other.api_dollars
        self.standard_credits += other.standard_credits
        self.adjusted_credits += other.adjusted_credits


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
class Aggregate:
    key: str
    label: str
    totals: TokenTotals = field(default_factory=TokenTotals)
    costs: CostTotals = field(default_factory=CostTotals)
    models: set[str] = field(default_factory=set)
    service_tiers: set[str] = field(default_factory=set)
    plan_types: set[str] = field(default_factory=set)
    usage_sources: set[str] = field(default_factory=set)
    model_context_window: int = 0
    long_context_events: int = 0
    unknown_model_events: int = 0
    unknown_tier_events: int = 0

    def add_event(
        self,
        event: UsageEvent,
        costs: CostTotals,
        long_context: bool,
        unknown_model: bool,
        unknown_tier: bool,
    ) -> None:
        self.totals.add_usage(event.usage)
        self.costs.add(costs)
        if event.model:
            self.models.add(event.model)
        if event.service_tier:
            self.service_tiers.add(event.service_tier)
        if event.plan_type:
            self.plan_types.add(event.plan_type)
        if event.usage_source:
            self.usage_sources.add(event.usage_source)
        self.model_context_window = max(self.model_context_window, event.model_context_window)
        self.long_context_events += int(long_context)
        self.unknown_model_events += int(unknown_model)
        self.unknown_tier_events += int(unknown_tier)


@dataclass(frozen=True)
class LoadResult:
    events: list[UsageEvent]
    duplicates: int
    tier_sources: dict[str, int]
    plan_types: set[str]
    credit_samples: list[RateLimitSample]
    warnings: list[str]
