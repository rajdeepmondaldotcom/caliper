from __future__ import annotations

from dataclasses import asdict, dataclass

from caliper.arbitrage_rules import HEURISTICS_VERSION, RULES
from caliper.models import UsageEvent


@dataclass(frozen=True)
class ArbitrageSuggestion:
    rule_id: str
    confidence: float
    evidence: dict[str, object]

    def to_record(self) -> dict[str, object]:
        return {"heuristics_version": HEURISTICS_VERSION, **asdict(self)}


def suggest(events: list[UsageEvent], threshold: float = 0.6) -> list[ArbitrageSuggestion]:
    suggestions: list[ArbitrageSuggestion] = []
    for event in events:
        suggestions.extend(_event_suggestions(event))
    return sorted(
        [item for item in suggestions if item.confidence >= threshold],
        key=lambda item: (-item.confidence, item.rule_id),
    )


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


def _evidence(event: UsageEvent) -> dict[str, object]:
    return {
        "session_id": event.session_id,
        "vendor": event.vendor,
        "model": event.model,
        "service_tier": event.service_tier,
        "timestamp": event.timestamp.isoformat(),
    }
