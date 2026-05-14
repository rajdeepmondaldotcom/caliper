from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal

from caliper.aggregation import event_cost
from caliper.arbitrage_rules import HEURISTICS_VERSION, RULES
from caliper.models import UsageEvent, decimal_string
from caliper.pricing import RateCard


@dataclass(frozen=True)
class ArbitrageSuggestion:
    rule_id: str
    confidence: float
    evidence: dict[str, object]

    def to_record(self) -> dict[str, object]:
        return {"heuristics_version": HEURISTICS_VERSION, **asdict(self)}


@dataclass(frozen=True)
class ArbitrageRecommendation:
    rule_id: str
    title: str
    detail: str
    action: str
    next_command: str
    confidence: float
    events: int
    sessions: int
    vendors: tuple[str, ...]
    models: tuple[str, ...]
    service_tiers: tuple[str, ...]
    target_model: str = ""
    target_service_tier: str = ""
    estimated_savings_usd_exact: str = "0"
    estimated_savings_note: str = ""
    examples: tuple[dict[str, object], ...] = ()

    def to_record(self) -> dict[str, object]:
        return {"heuristics_version": HEURISTICS_VERSION, **asdict(self)}


@dataclass
class _RecommendationBucket:
    rule_id: str
    target_model: str
    target_service_tier: str
    confidence_sum: float = 0.0
    events: int = 0
    sessions: set[str] | None = None
    vendors: set[str] | None = None
    models: set[str] | None = None
    service_tiers: set[str] | None = None
    savings: Decimal = Decimal("0")
    examples: list[dict[str, object]] | None = None

    def __post_init__(self) -> None:
        self.sessions = set()
        self.vendors = set()
        self.models = set()
        self.service_tiers = set()
        self.examples = []

    def add(
        self,
        suggestion: ArbitrageSuggestion,
        event: UsageEvent,
        *,
        savings: Decimal,
    ) -> None:
        self.events += 1
        self.confidence_sum += suggestion.confidence
        self.savings += savings
        self.sessions.add(event.session_id)
        self.vendors.add(event.vendor or "unknown")
        self.models.add(event.model or "unknown")
        self.service_tiers.add(event.service_tier or "unknown")
        if len(self.examples) < 5:
            self.examples.append(suggestion.evidence)

    def recommendation(self) -> ArbitrageRecommendation:
        rule = RULES[self.rule_id]
        confidence = self.confidence_sum / max(self.events, 1)
        target = _target_phrase(self.target_model, self.target_service_tier)
        savings_note = (
            "Estimated by re-pricing matching events."
            if self.savings > 0
            else _zero_savings_note(self.rule_id)
        )
        detail = f"{self.events:,} matching events across {len(self.sessions):,} sessions. {target}"
        next_command = _next_command_for(
            self.rule_id,
            self.target_model,
            self.target_service_tier,
        )
        return ArbitrageRecommendation(
            rule_id=self.rule_id,
            title=rule.title,
            detail=detail,
            action=_action_for(self.rule_id, self.target_model, self.target_service_tier),
            next_command=next_command,
            confidence=round(confidence, 3),
            events=self.events,
            sessions=len(self.sessions),
            vendors=tuple(sorted(self.vendors)),
            models=tuple(sorted(self.models)),
            service_tiers=tuple(sorted(self.service_tiers)),
            target_model=self.target_model,
            target_service_tier=self.target_service_tier,
            estimated_savings_usd_exact=decimal_string(self.savings),
            estimated_savings_note=savings_note,
            examples=tuple(self.examples),
        )


def suggest(events: list[UsageEvent], threshold: float = 0.6) -> list[ArbitrageSuggestion]:
    suggestions: list[ArbitrageSuggestion] = []
    for event in events:
        suggestions.extend(_event_suggestions(event))
    return sorted(
        [item for item in suggestions if item.confidence >= threshold],
        key=lambda item: (-item.confidence, item.rule_id),
    )


def recommend(
    events: list[UsageEvent],
    rate_card: RateCard,
    threshold: float = 0.6,
    *,
    limit: int = 10,
) -> list[ArbitrageRecommendation]:
    buckets: dict[tuple[str, str, str], _RecommendationBucket] = {}
    for event in events:
        for suggestion in _event_suggestions(event):
            if suggestion.confidence < threshold:
                continue
            target_model, target_tier = _target_for(suggestion.rule_id, event)
            key = (suggestion.rule_id, target_model, target_tier)
            bucket = buckets.setdefault(
                key,
                _RecommendationBucket(
                    rule_id=suggestion.rule_id,
                    target_model=target_model,
                    target_service_tier=target_tier,
                ),
            )
            bucket.add(
                suggestion,
                event,
                savings=_estimated_savings(event, rate_card, target_model, target_tier),
            )
    rows = [bucket.recommendation() for bucket in buckets.values()]
    return sorted(
        rows,
        key=lambda item: (
            -Decimal(item.estimated_savings_usd_exact),
            -item.confidence,
            -item.events,
            item.rule_id,
        ),
    )[:limit]


def explain(rule_id: str) -> dict[str, str]:
    if rule_id not in RULES:
        raise ValueError(f"unknown rule_id: {rule_id}")
    rule = RULES[rule_id]
    return {
        "heuristics_version": HEURISTICS_VERSION,
        "rule_id": rule.rule_id,
        "title": rule.title,
        "explanation": rule.explanation,
    }


def _event_suggestions(event: UsageEvent) -> list[ArbitrageSuggestion]:
    suggestions: list[ArbitrageSuggestion] = []
    model = event.model.lower()
    if _is_premium(model) and event.usage.input_tokens < 2_000:
        suggestions.append(
            ArbitrageSuggestion(
                rule_id="premium-short-context",
                confidence=0.7,
                evidence=_evidence(event) | {"input_tokens": event.usage.input_tokens},
            )
        )
    if event.service_tier == "fast" and event.usage.output_tokens < 500:
        suggestions.append(
            ArbitrageSuggestion(
                rule_id="fast-tier-low-output",
                confidence=0.65,
                evidence=_evidence(event) | {"output_tokens": event.usage.output_tokens},
            )
        )
    if "opus" in model and event.usage.reasoning_output_tokens == 0:
        suggestions.append(
            ArbitrageSuggestion(
                rule_id="opus-no-reasoning",
                confidence=0.8,
                evidence=_evidence(event),
            )
        )
    return suggestions


def _is_premium(model: str) -> bool:
    return "opus" in model or model in {"gpt-5.5", "gpt-5.4"}


def _target_for(rule_id: str, event: UsageEvent) -> tuple[str, str]:
    model = event.model.lower()
    if rule_id == "fast-tier-low-output":
        return "", "standard"
    if "opus" in model:
        return "claude-sonnet-4.6", ""
    if model in {"gpt-5.5", "gpt-5.4"}:
        return "gpt-5.4-mini", ""
    return "", ""


def _estimated_savings(
    event: UsageEvent,
    rate_card: RateCard,
    target_model: str,
    target_tier: str,
) -> Decimal:
    if not target_model and not target_tier:
        return Decimal("0")
    actual, _, _ = event_cost(rate_card, event)
    hypothetical = replace(
        event,
        model=target_model or event.model,
        service_tier=target_tier or event.service_tier,
        vendor_reported_cost_usd=None,
    )
    projected, _, _ = event_cost(rate_card, hypothetical)
    return max(Decimal("0"), actual.cost_usd - projected.cost_usd)


def _target_phrase(model: str, tier: str) -> str:
    if model and tier:
        return f"Test model={model} and tier={tier}."
    if model:
        return f"Test model={model}."
    if tier:
        return f"Test tier={tier}."
    return "Inspect the matching sessions before changing defaults."


def _action_for(rule_id: str, model: str, tier: str) -> str:
    return _next_command_for(rule_id, model, tier) or "caliper session --top 10"


def _next_command_for(rule_id: str, model: str, tier: str) -> str:
    del rule_id
    parts = ["caliper whatif"]
    if model:
        parts.extend(["--hypothetical-model", model])
    if tier:
        parts.extend(["--hypothetical-service-tier", tier])
    return " ".join(parts) if len(parts) > 2 else "caliper advise --strict"


def _zero_savings_note(rule_id: str) -> str:
    if rule_id == "fast-tier-low-output":
        return "USD API-equivalent cost is unchanged; this is a credit-window and latency lever."
    return "No USD savings could be priced from the active rate card."


def _evidence(event: UsageEvent) -> dict[str, object]:
    return {
        "session_id": event.session_id,
        "vendor": event.vendor,
        "model": event.model,
        "service_tier": event.service_tier,
        "timestamp": event.timestamp.isoformat(),
    }
