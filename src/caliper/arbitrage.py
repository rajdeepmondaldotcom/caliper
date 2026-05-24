from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal

from caliper.aggregation import event_cost
from caliper.arbitrage_rules import HEURISTICS_VERSION, RULES
from caliper.humanize import session_display_label
from caliper.models import UsageEvent, decimal_string
from caliper.pricing import MODELS_BY_NAME, RateCard, model_vendor, normalize_model


@dataclass(frozen=True)
class ArbitrageSuggestion:
    rule_id: str
    confidence: float
    evidence: dict[str, object]

    def to_record(self) -> dict[str, object]:
        return {"heuristics_version": HEURISTICS_VERSION, **asdict(self)}


@dataclass(frozen=True)
class ModelAlternative:
    model: str
    vendor: str
    projected_cost_usd_exact: str
    estimated_savings_usd_exact: str
    events: int = 0

    def to_record(self) -> dict[str, object]:
        return asdict(self)


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
    alternatives: tuple[ModelAlternative, ...] = ()

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
    model_alternatives: dict[str, _AlternativeTotals] | None = None

    def __post_init__(self) -> None:
        self.sessions = set()
        self.vendors = set()
        self.models = set()
        self.service_tiers = set()
        self.examples = []
        self.model_alternatives = {}

    def add(
        self,
        suggestion: ArbitrageSuggestion,
        event: UsageEvent,
        *,
        savings: Decimal,
        alternatives: tuple[ModelAlternative, ...] = (),
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
        for alternative in alternatives:
            priority = _alternative_priority(event.model, alternative.model)
            total = self.model_alternatives.setdefault(
                alternative.model,
                _AlternativeTotals(
                    model=alternative.model,
                    vendor=alternative.vendor,
                    priority=priority,
                ),
            )
            total.priority = min(total.priority, priority)
            total.projected += Decimal(alternative.projected_cost_usd_exact)
            total.savings += Decimal(alternative.estimated_savings_usd_exact)
            total.events += alternative.events

    def recommendation(self) -> ArbitrageRecommendation:
        rule = RULES[self.rule_id]
        confidence = self.confidence_sum / max(self.events, 1)
        alternatives = self.ranked_alternatives(limit=3)
        target_model = alternatives[0].model if alternatives else self.target_model
        savings = (
            Decimal(alternatives[0].estimated_savings_usd_exact) if alternatives else self.savings
        )
        target = _target_phrase(target_model, self.target_service_tier, alternatives)
        savings_note = (
            "Estimated by re-pricing matching events."
            if savings > 0
            else _zero_savings_note(self.rule_id)
        )
        detail = f"{self.events:,} matching events across {len(self.sessions):,} sessions. {target}"
        next_command = _next_command_for(
            self.rule_id,
            target_model,
            self.target_service_tier,
        )
        return ArbitrageRecommendation(
            rule_id=self.rule_id,
            title=rule.title,
            detail=detail,
            action=_action_for(self.rule_id, target_model, self.target_service_tier),
            next_command=next_command,
            confidence=round(confidence, 3),
            events=self.events,
            sessions=len(self.sessions),
            vendors=tuple(sorted(self.vendors)),
            models=tuple(sorted(self.models)),
            service_tiers=tuple(sorted(self.service_tiers)),
            target_model=target_model,
            target_service_tier=self.target_service_tier,
            estimated_savings_usd_exact=decimal_string(savings),
            estimated_savings_note=savings_note,
            examples=tuple(self.examples),
            alternatives=alternatives,
        )

    def ranked_alternatives(self, *, limit: int = 3) -> tuple[ModelAlternative, ...]:
        if not self.model_alternatives:
            return ()
        rows = [
            total.to_alternative()
            for total in self.model_alternatives.values()
            if total.savings > 0
        ]
        rows.sort(
            key=lambda item: (
                self.model_alternatives[item.model].priority,
                -Decimal(item.estimated_savings_usd_exact),
                Decimal(item.projected_cost_usd_exact),
                item.vendor,
                item.model,
            )
        )
        return tuple(rows[:limit])


@dataclass
class _AlternativeTotals:
    model: str
    vendor: str
    projected: Decimal = Decimal("0")
    savings: Decimal = Decimal("0")
    events: int = 0
    priority: int = 50

    def to_alternative(self) -> ModelAlternative:
        return ModelAlternative(
            model=self.model,
            vendor=self.vendor,
            projected_cost_usd_exact=decimal_string(self.projected),
            estimated_savings_usd_exact=decimal_string(self.savings),
            events=self.events,
        )


def suggest(
    events: list[UsageEvent],
    threshold: float = 0.6,
    *,
    rate_card: RateCard | None = None,
) -> list[ArbitrageSuggestion]:
    """Yield individual heuristic flags (the pre-aggregated form).

    ``rate_card`` is optional so that legacy callers without a built
    catalog still work — when omitted, the function loads a default
    rate card. The default carries the built-in :data:`MODELS_BY_NAME`
    table, which is enough to price ranked model alternatives offline.
    """
    card = rate_card if rate_card is not None else RateCard.load(None, "model")
    suggestions: list[ArbitrageSuggestion] = []
    for event in events:
        suggestions.extend(_event_suggestions(event, card))
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
        for suggestion in _event_suggestions(event, rate_card):
            if suggestion.confidence < threshold:
                continue
            alternatives: tuple[ModelAlternative, ...] = ()
            target_model, target_tier = "", ""
            if _rule_targets_model(suggestion.rule_id):
                alternatives = model_alternatives_for_event(event, rate_card, limit=3)
                if not alternatives:
                    continue
                target_model = alternatives[0].model
            else:
                target_tier = _target_tier_for(suggestion.rule_id)
            key = (
                suggestion.rule_id,
                "" if alternatives else target_model,
                target_tier,
            )
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
                alternatives=alternatives,
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


def _event_suggestions(event: UsageEvent, rate_card: RateCard) -> list[ArbitrageSuggestion]:
    """Yield raw heuristic flags for ``event``.

    "Premium" is no longer a hard-coded list. A model is a candidate
    when the active rate card can price a cheaper alternative for the
    same token shape, including cross-vendor alternatives.
    """
    suggestions: list[ArbitrageSuggestion] = []
    model = event.model.lower()
    alternatives = model_alternatives_for_event(event, rate_card, limit=1)
    has_alternative = bool(alternatives)
    if has_alternative and event.usage.input_tokens < 2_000:
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
    if "opus" in model and event.usage.reasoning_output_tokens == 0 and has_alternative:
        suggestions.append(
            ArbitrageSuggestion(
                rule_id="opus-no-reasoning",
                confidence=0.8,
                evidence=_evidence(event),
            )
        )
    return suggestions


def rank_model_alternatives(
    events: list[UsageEvent],
    rate_card: RateCard,
    *,
    limit: int = 3,
) -> tuple[ModelAlternative, ...]:
    totals: dict[str, _AlternativeTotals] = {}
    for event in events:
        for alternative in model_alternatives_for_event(event, rate_card, limit=0):
            priority = _alternative_priority(event.model, alternative.model)
            total = totals.setdefault(
                alternative.model,
                _AlternativeTotals(
                    model=alternative.model,
                    vendor=alternative.vendor,
                    priority=priority,
                ),
            )
            total.priority = min(total.priority, priority)
            total.projected += Decimal(alternative.projected_cost_usd_exact)
            total.savings += Decimal(alternative.estimated_savings_usd_exact)
            total.events += alternative.events
    rows = [total.to_alternative() for total in totals.values() if total.savings > 0]
    rows.sort(
        key=lambda item: (
            totals[item.model].priority,
            -Decimal(item.estimated_savings_usd_exact),
            Decimal(item.projected_cost_usd_exact),
            item.vendor,
            item.model,
        )
    )
    return tuple(rows[:limit])


def model_alternatives_for_event(
    event: UsageEvent,
    rate_card: RateCard,
    *,
    limit: int = 3,
) -> tuple[ModelAlternative, ...]:
    actual, _, _ = event_cost(rate_card, event)
    if actual.cost_usd <= 0:
        return ()
    source = normalize_model(event.model)
    rows: list[ModelAlternative] = []
    for candidate in _candidate_model_names(rate_card):
        if candidate == source:
            continue
        if not _is_recommendable_replacement(candidate):
            continue
        projected, _, unknown_model = rate_card.cost_for(
            event.usage,
            candidate,
            event.service_tier,
        )
        if unknown_model or projected.unpriced_events or projected.cost_usd <= 0:
            continue
        savings = actual.cost_usd - projected.cost_usd
        if savings <= 0:
            continue
        rows.append(
            ModelAlternative(
                model=candidate,
                vendor=model_vendor(candidate) or "unknown",
                projected_cost_usd_exact=decimal_string(projected.cost_usd),
                estimated_savings_usd_exact=decimal_string(savings),
                events=1,
            )
        )
    rows.sort(
        key=lambda item: (
            _alternative_priority(event.model, item.model),
            -Decimal(item.estimated_savings_usd_exact),
            Decimal(item.projected_cost_usd_exact),
            item.vendor,
            item.model,
        )
    )
    return tuple(rows if limit <= 0 else rows[:limit])


def _candidate_model_names(rate_card: RateCard) -> tuple[str, ...]:
    seen: set[str] = set()
    names: list[str] = []
    for raw in list(rate_card.catalog_cards) + list(MODELS_BY_NAME):
        name = normalize_model(raw)
        if not name or name in seen:
            continue
        card = rate_card.catalog_cards.get(name) or MODELS_BY_NAME.get(name)
        if card is None or card.api_rates is None:
            continue
        seen.add(name)
        names.append(name)
    return tuple(names)


def _is_recommendable_replacement(candidate: str) -> bool:
    # Haiku remains priced for what-if aliases and historical logs, but the
    # dashboard should not present it as the modern replacement path.
    return "haiku" not in candidate


def _alternative_priority(source_model: str, candidate: str) -> int:
    source_vendor = model_vendor(source_model)
    candidate_vendor = model_vendor(candidate)
    if source_vendor == "anthropic" and candidate == "claude-sonnet-4.6":
        return 0
    if source_vendor == "openai" and candidate == "gpt-5.4":
        return 0
    if source_vendor == candidate_vendor:
        return 10
    if candidate == "gpt-5.4":
        return 20
    if candidate == "gpt-5.4-mini":
        return 30
    if candidate == "gpt-5.5":
        return 40
    return 50


def _rule_targets_model(rule_id: str) -> bool:
    return rule_id != "fast-tier-low-output"


def _target_tier_for(rule_id: str) -> str:
    return "standard" if rule_id == "fast-tier-low-output" else ""


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


def _target_phrase(
    model: str,
    tier: str,
    alternatives: tuple[ModelAlternative, ...] = (),
) -> str:
    if alternatives:
        choices = ", ".join(
            f"{item.model} ({item.vendor}, saves "
            f"{_format_money_exact(item.estimated_savings_usd_exact)})"
            for item in alternatives
        )
        return f"Test current alternatives: {choices}."
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


def _format_money_exact(value: str) -> str:
    amount = Decimal(value or "0")
    if amount == 0:
        return "$0"
    if abs(amount) < Decimal("0.01"):
        return f"${amount:,.4f}"
    return f"${amount:,.2f}"


def _zero_savings_note(rule_id: str) -> str:
    if rule_id == "fast-tier-low-output":
        return "USD API-equivalent cost is unchanged; this is a credit-window and latency lever."
    return "No USD savings could be priced from the active rate card."


def _evidence(event: UsageEvent) -> dict[str, object]:
    return {
        "session": session_display_label(event, "UTC"),
        "session_id": event.session_id,
        "vendor": event.vendor,
        "model": event.model,
        "service_tier": event.service_tier,
        "timestamp": event.timestamp.isoformat(),
    }
