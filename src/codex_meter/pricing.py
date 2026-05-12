"""Embedded Codex rate card + RateCard resolver (offline-first)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from codex_meter.models import CostTotals, LongContextRule, PricingSource, Rates, Usage

LONG_CONTEXT_INPUT_THRESHOLD = 272_000

DEFAULT_API_RATES = Rates(input=5.0, cached_input=0.5, output=30.0)
DEFAULT_CREDIT_RATES = Rates(input=125.0, cached_input=12.5, output=750.0)

GPT55_LONG_CONTEXT = LongContextRule(
    threshold=LONG_CONTEXT_INPUT_THRESHOLD, input_mult=2.0, output_mult=1.5
)


@dataclass(frozen=True)
class ModelCard:
    """One Codex model's pricing. `api_rates` may be None for credit-only models."""

    name: str
    api_rates: Rates | None
    credit_rates: Rates
    fast_multiplier: float = 1.0
    long_context: LongContextRule | None = None


MODEL_CARDS: tuple[ModelCard, ...] = (
    ModelCard(
        name="gpt-5.5",
        api_rates=Rates(5.0, 0.5, 30.0),
        credit_rates=Rates(125.0, 12.5, 750.0),
        fast_multiplier=2.5,
        long_context=GPT55_LONG_CONTEXT,
    ),
    ModelCard(
        name="gpt-5.4",
        api_rates=Rates(2.5, 0.25, 15.0),
        credit_rates=Rates(62.5, 6.25, 375.0),
        fast_multiplier=2.0,
    ),
    ModelCard(
        name="gpt-5.4-mini",
        api_rates=Rates(0.75, 0.075, 4.5),
        credit_rates=Rates(18.75, 1.875, 113.0),
    ),
    ModelCard(
        name="gpt-5.3-codex",
        api_rates=Rates(1.75, 0.175, 14.0),
        credit_rates=Rates(43.75, 4.375, 350.0),
    ),
    ModelCard(
        name="gpt-5.2",
        api_rates=Rates(1.75, 0.175, 14.0),
        credit_rates=Rates(43.75, 4.375, 350.0),
    ),
    ModelCard(
        name="gpt-5.1-codex-max",
        api_rates=None,
        credit_rates=Rates(31.25, 3.125, 250.0),
    ),
)

MODELS_BY_NAME: dict[str, ModelCard] = {card.name: card for card in MODEL_CARDS}

PRICING_SOURCES = [
    PricingSource(
        name="OpenAI API pricing",
        url="https://openai.com/api/pricing/",
        checked="2026-05-12",
    ),
    PricingSource(
        name="GPT-5.5 model pricing and long-context rule",
        url="https://developers.openai.com/api/docs/models/gpt-5.5",
        checked="2026-05-12",
    ),
    PricingSource(
        name="Codex rate card",
        url="https://help.openai.com/en/articles/20001106-codex-rate-card",
        checked="2026-05-12",
    ),
]


def normalize_model(model: str | None) -> str:
    raw = (model or "").strip().lower()
    if not raw:
        return ""
    aliases = {
        "gpt-5.4-mini": ("gpt-5.4-mini", "gpt-5-4-mini"),
        "gpt-5.3-codex": ("gpt-5.3-codex", "gpt-5-3-codex"),
        "gpt-5.1-codex-max": ("gpt-5.1-codex-max", "gpt-5-1-codex-max"),
    }
    for normalized, prefixes in aliases.items():
        if raw in prefixes or any(raw.startswith(f"{prefix}-") for prefix in prefixes):
            return normalized
    for known in sorted(MODELS_BY_NAME, key=len, reverse=True):
        if raw == known or raw.startswith(f"{known}-"):
            return known
    return raw


def normalize_service_tier(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {"fast", "priority"}:
        return "fast"
    if raw in {"standard", "default", "regular"}:
        return "standard"
    return ""


def _parse_overrides(raw: object, section: str) -> dict[str, Rates]:
    if not isinstance(raw, dict):
        return {}
    values = raw.get(section, {})
    if not isinstance(values, dict):
        raise ValueError(f"rates file section {section!r} must be an object")
    parsed: dict[str, Rates] = {}
    for model, item in values.items():
        if not isinstance(item, dict):
            raise ValueError(f"rates for {model!r} must be an object")
        reasoning_raw = item.get("reasoning_output")
        parsed[normalize_model(model)] = Rates(
            input=float(item["input"]),
            cached_input=float(item["cached_input"]),
            output=float(item["output"]),
            reasoning_output=float(reasoning_raw) if reasoning_raw is not None else None,
        )
    return parsed


@dataclass(frozen=True)
class RateCard:
    """Per-run rate resolver. Loads any local overrides exactly once."""

    api_overrides: dict[str, Rates]
    credit_overrides: dict[str, Rates]
    pricing_mode: str

    @classmethod
    def load(cls, path: Path | None, pricing_mode: str = "model") -> RateCard:
        if path is None:
            return cls(api_overrides={}, credit_overrides={}, pricing_mode=pricing_mode)
        try:
            raw = json.loads(path.expanduser().read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read rates file {path}: {exc}") from exc
        return cls(
            api_overrides=_parse_overrides(raw, "api"),
            credit_overrides=_parse_overrides(raw, "credits"),
            pricing_mode=pricing_mode,
        )

    def cost_for(
        self, usage: Usage, model: str, service_tier: str
    ) -> tuple[CostTotals, bool, bool]:
        normalized = normalize_model(model)
        flat = self.pricing_mode == "flat"
        card = MODELS_BY_NAME.get(normalized)
        rule = card.long_context if (card and not flat) else None
        long_context = rule is not None and usage.input_tokens > rule.threshold
        input_mult = rule.input_mult if long_context and rule else 1.0
        output_mult = rule.output_mult if long_context and rule else 1.0
        api_rates, unknown_api = self._resolve_api_rates(normalized, card, flat)
        credit_rates, unknown_credit = self._resolve_credit_rates(normalized, card, flat)
        standard_credits = _estimate(usage, credit_rates, input_mult, output_mult)
        adjusted_credits = standard_credits
        if service_tier == "fast" and card is not None:
            adjusted_credits = standard_credits * card.fast_multiplier
        return (
            CostTotals(
                api_dollars=_estimate(usage, api_rates, input_mult, output_mult),
                standard_credits=standard_credits,
                adjusted_credits=adjusted_credits,
            ),
            long_context,
            unknown_api or unknown_credit,
        )

    def _resolve_api_rates(
        self, normalized: str, card: ModelCard | None, flat: bool
    ) -> tuple[Rates, bool]:
        if flat:
            return DEFAULT_API_RATES, False
        if normalized in self.api_overrides:
            return self.api_overrides[normalized], False
        if card and card.api_rates is not None:
            return card.api_rates, False
        return DEFAULT_API_RATES, card is None

    def _resolve_credit_rates(
        self, normalized: str, card: ModelCard | None, flat: bool
    ) -> tuple[Rates, bool]:
        if flat:
            return DEFAULT_CREDIT_RATES, False
        if normalized in self.credit_overrides:
            return self.credit_overrides[normalized], False
        if card:
            return card.credit_rates, False
        return DEFAULT_CREDIT_RATES, True


def _estimate(usage: Usage, rates: Rates, input_mult: float, output_mult: float) -> float:
    return (
        usage.uncached_input_tokens * rates.input * input_mult
        + usage.cached_input_tokens * rates.cached_input * input_mult
        + usage.output_tokens * rates.output * output_mult
        + usage.reasoning_output_tokens * rates.effective_reasoning_output * output_mult
    ) / 1_000_000


def estimate_event_cost(
    usage: Usage,
    model: str,
    service_tier: str,
    pricing_mode: str,
    rates_file: Path | None = None,
) -> tuple[CostTotals, bool, bool]:
    """Single-event pricing. Builds a fresh RateCard — prefer caching one per run."""
    card = RateCard.load(rates_file, pricing_mode)
    return card.cost_for(usage, model, service_tier)
