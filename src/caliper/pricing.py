"""Embedded Codex rate card + RateCard resolver (offline-first)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from caliper import taxonomy as _taxonomy
from caliper.models import (
    CostTotals,
    LongContextRule,
    PricingSource,
    Rates,
    RuntimeOptions,
    Usage,
    decimal_value,
)
from caliper.pricing_catalog import (
    PricingCatalog,
    available_catalog_models,
    catalog_age_hours,
    load_cached_catalog,
    load_pricing_catalog,
)

LONG_CONTEXT_INPUT_THRESHOLD = 272_000
ZERO = Decimal("0")
FAST_TIER_COST_MULTIPLIERS = {
    "gpt-5.5": Decimal("2.5"),
    "gpt-5.4": Decimal("2"),
    "gpt-5.4-mini": Decimal("2"),
    "gpt-5.4-nano": Decimal("2"),
}

DEFAULT_API_RATES = Rates(input=5.0, cached_input=0.5, output=30.0)
LONG_CONTEXT_1050K = LongContextRule(
    threshold=LONG_CONTEXT_INPUT_THRESHOLD, input_mult=2.0, output_mult=1.5
)


@dataclass(frozen=True)
class ModelCard:
    """One model's USD pricing. Missing rates are intentionally unpriced."""

    name: str
    api_rates: Rates | None
    long_context: LongContextRule | None = None


MODEL_CARDS: tuple[ModelCard, ...] = (
    ModelCard(
        name="gpt-5.5",
        api_rates=Rates(5.0, 0.5, 30.0),
        long_context=LONG_CONTEXT_1050K,
    ),
    ModelCard(
        name="gpt-5.4",
        api_rates=Rates(2.5, 0.25, 15.0),
        long_context=LONG_CONTEXT_1050K,
    ),
    ModelCard(
        name="gpt-5.4-mini",
        api_rates=Rates(0.75, 0.075, 4.5),
    ),
    ModelCard(
        name="gpt-5.3-codex",
        api_rates=Rates(1.75, 0.175, 14.0),
    ),
    ModelCard(
        name="gpt-5.2",
        api_rates=Rates(1.75, 0.175, 14.0),
    ),
    ModelCard(
        name="gpt-5.1-codex-max",
        api_rates=Rates(1.25, 0.125, 10.0),
    ),
    ModelCard(
        name="claude-haiku-4.5",
        api_rates=Rates(
            1.0,
            0.10,
            5.0,
            cache_creation_input=1.25,
            cache_creation_input_1h=2.0,
        ),
    ),
    ModelCard(
        name="claude-sonnet-4.6",
        api_rates=Rates(
            3.0,
            0.30,
            15.0,
            cache_creation_input=3.75,
            cache_creation_input_1h=6.0,
        ),
    ),
    ModelCard(
        name="claude-opus-4.7",
        api_rates=Rates(
            5.0,
            0.50,
            25.0,
            cache_creation_input=6.25,
            cache_creation_input_1h=10.0,
        ),
    ),
)

MODELS_BY_NAME: dict[str, ModelCard] = {card.name: card for card in MODEL_CARDS}


KNOWN_MODEL_VENDORS = _taxonomy.KNOWN_MODEL_VENDORS
VENDOR_ANTHROPIC = _taxonomy.VENDOR_ANTHROPIC
VENDOR_OPENAI = _taxonomy.VENDOR_OPENAI
VENDOR_ANYSPHERE = _taxonomy.VENDOR_ANYSPHERE
VENDOR_GOOGLE = _taxonomy.VENDOR_GOOGLE
VENDOR_MISTRAL = _taxonomy.VENDOR_MISTRAL
VENDOR_META = _taxonomy.VENDOR_META
VENDOR_UNKNOWN = _taxonomy.VENDOR_UNKNOWN


def model_vendor(model: str | None) -> str:
    """Return the canonical vendor label for a model id."""
    return _taxonomy.model_vendor(model)


def model_vendor_glyph(vendor: str) -> str:
    """Short single-character glyph for the dense Models screen header."""
    return _taxonomy.model_vendor_glyph(vendor)


PRICING_SOURCES = [
    PricingSource(
        name="OpenAI API pricing",
        url="https://openai.com/api/pricing/",
        checked="2026-05-22",
    ),
    PricingSource(
        name="GPT-5.5 model pricing and long-context rule",
        url="https://developers.openai.com/api/docs/models",
        checked="2026-05-22",
    ),
    PricingSource(
        name="GPT-5.4 model pricing and long-context rule",
        url="https://developers.openai.com/api/docs/models",
        checked="2026-05-22",
    ),
    PricingSource(
        name="Codex rate card",
        url="https://help.openai.com/en/articles/20001106-codex-rate-card",
        checked="2026-05-13",
    ),
    PricingSource(
        name="Codex subscription access and limits",
        url="https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan",
        checked="2026-05-13",
    ),
    PricingSource(
        name="Codex pricing and usage-limit dashboard",
        url="https://developers.openai.com/codex/pricing",
        checked="2026-05-13",
    ),
    PricingSource(
        name="Codex fast mode multipliers",
        url="https://developers.openai.com/codex/speed",
        checked="2026-05-22",
    ),
    PricingSource(
        name="GPT-5.1-Codex-Max model pricing",
        url="https://developers.openai.com/api/docs/models/gpt-5.1-codex-max",
        checked="2026-05-13",
    ),
    PricingSource(
        name="Anthropic API pricing",
        url="https://platform.claude.com/docs/en/about-claude/pricing",
        checked="2026-05-22",
    ),
    PricingSource(
        name="Anthropic prompt caching (cache write 1.25x, cache read 0.1x)",
        url="https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching",
        checked="2026-05-13",
    ),
    PricingSource(
        name="Claude Haiku 4.5 model pricing",
        url="https://platform.claude.com/docs/en/about-claude/models/overview",
        checked="2026-05-22",
    ),
    PricingSource(
        name="Claude Sonnet 4.6 model pricing",
        url="https://platform.claude.com/docs/en/about-claude/models/overview",
        checked="2026-05-22",
    ),
    PricingSource(
        name="Claude Opus 4.7 model pricing",
        url="https://platform.claude.com/docs/en/about-claude/models/overview",
        checked="2026-05-22",
    ),
    PricingSource(
        name="Anthropic extended cache (1h cache write 2x)",
        url="https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching#1-hour-cache-duration",
        checked="2026-05-13",
    ),
]


@lru_cache(maxsize=4096)
def normalize_model(model: str | None) -> str:
    raw = (model or "").strip().lower()
    if not raw:
        return ""
    aliases = {
        "gpt-5.2-codex": ("gpt-5.2-codex", "gpt-5-2-codex"),
        "gpt-5.1-codex-max": ("gpt-5.1-codex-max", "gpt-5-1-codex-max"),
        "gpt-5.1-codex-mini": ("gpt-5.1-codex-mini", "gpt-5-1-codex-mini"),
        "gpt-5.1-codex": ("gpt-5.1-codex", "gpt-5-1-codex"),
        "gpt-5-codex": ("gpt-5-codex",),
        "gpt-5.4-mini": ("gpt-5.4-mini", "gpt-5-4-mini"),
        "gpt-5.3-codex-spark": ("gpt-5.3-codex-spark", "gpt-5-3-codex-spark"),
        "gpt-5.3-codex": ("gpt-5.3-codex", "gpt-5-3-codex"),
        "claude-haiku-4.5": ("claude-haiku-4.5", "claude-haiku-4-5"),
        "claude-sonnet-4.6": ("claude-sonnet-4.6", "claude-sonnet-4-6"),
        "claude-sonnet-4.5": ("claude-sonnet-4.5", "claude-sonnet-4-5"),
        "claude-opus-4.7": ("claude-opus-4.7", "claude-opus-4-7"),
        "claude-opus-4.6": ("claude-opus-4.6", "claude-opus-4-6"),
        "claude-opus-4.5": ("claude-opus-4.5", "claude-opus-4-5"),
        "claude-opus-4.1": ("claude-opus-4.1", "claude-opus-4-1"),
    }
    for normalized, prefixes in aliases.items():
        if raw in prefixes or any(_is_snapshot_variant(raw, prefix) for prefix in prefixes):
            return normalized
    for known in sorted(MODELS_BY_NAME, key=len, reverse=True):
        if raw == known or _is_snapshot_variant(raw, known):
            return known
    return raw


def resolve_hypothetical_model_alias(
    model: str | None,
    *,
    available_models: set[str] | None = None,
) -> str:
    """Resolve user-facing what-if aliases to a priced model id.

    This is intentionally narrower than :func:`normalize_model`: it accepts
    old family names people naturally type in scenario planning and maps them
    to the newest matching model that the active rate card can price.
    """

    normalized = normalize_model(model)
    if not normalized:
        return ""
    alias_candidates = _WHATIF_MODEL_ALIAS_CANDIDATES.get(_alias_key(model))
    available = available_model_names() if available_models is None else available_models
    if alias_candidates is None and normalized in available:
        return normalized
    if alias_candidates is None:
        return normalized
    for candidate in alias_candidates:
        if candidate in available:
            return candidate
    return alias_candidates[-1]


def _is_snapshot_variant(raw: str, prefix: str) -> bool:
    if not raw.startswith(f"{prefix}-"):
        return False
    suffix = raw.removeprefix(f"{prefix}-")
    return bool(
        suffix in {"latest", "preview"}
        or suffix.startswith("preview-")
        or suffix.startswith("snapshot-")
        or _looks_like_model_date(suffix)
    )


def _looks_like_model_date(value: str) -> bool:
    return bool(re.fullmatch(r"20\d{2}(-?\d{2}){0,2}([-.].*)?", value))


def normalize_service_tier(value: str | None) -> str:
    raw = (value or "").strip().lower()
    raw = raw.replace("_", "-")
    if raw in {"fast", "priority", "high", "xhigh", "x-high", "max"}:
        return "fast"
    if raw in {"standard", "default", "regular"}:
        return "standard"
    return ""


def service_tier_cost_multiplier(model: str | None, service_tier: str | None) -> Decimal:
    """Return the Codex credit multiplier implied by the service tier.

    OpenAI documents fast-mode multipliers by model family. We only apply the
    multiplier where the active model family has a documented multiplier; all
    other models remain at 1x until a sourced multiplier exists.
    """

    if normalize_service_tier(service_tier) != "fast":
        return Decimal("1")
    normalized = normalize_model(model)
    if normalized in FAST_TIER_COST_MULTIPLIERS:
        return FAST_TIER_COST_MULTIPLIERS[normalized]
    if normalized.startswith("gpt-5.4-"):
        return FAST_TIER_COST_MULTIPLIERS["gpt-5.4"]
    return Decimal("1")


def _alias_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


_WHATIF_MODEL_ALIAS_CANDIDATES: dict[str, tuple[str, ...]] = {
    "haiku": ("claude-haiku-4.5",),
    "claude-haiku": ("claude-haiku-4.5",),
    "claude-haiku-latest": ("claude-haiku-4.5",),
    "claude-3-haiku": ("claude-haiku-4.5",),
    "claude-3-5-haiku": ("claude-haiku-4.5",),
    "claude-3-7-haiku": ("claude-haiku-4.5",),
    "sonnet": ("claude-sonnet-4.6",),
    "claude-sonnet": ("claude-sonnet-4.6",),
    "claude-sonnet-latest": ("claude-sonnet-4.6",),
    "claude-3-sonnet": ("claude-sonnet-4.6",),
    "claude-3-5-sonnet": ("claude-sonnet-4.6",),
    "claude-3-7-sonnet": ("claude-sonnet-4.6",),
    "opus": ("claude-opus-4.7",),
    "claude-opus": ("claude-opus-4.7",),
    "claude-opus-latest": ("claude-opus-4.7",),
    "claude-3-opus": ("claude-opus-4.7",),
    "gpt-mini": ("gpt-5.4-mini",),
    "mini": ("gpt-5.4-mini",),
    "gpt-5-mini": ("gpt-5.4-mini",),
    "gpt-5-5-mini": ("gpt-5.4-mini",),
    "gpt-5-4-mini": ("gpt-5.4-mini",),
    "gpt-nano": ("gpt-5.4-nano", "gpt-5.4-mini"),
    "nano": ("gpt-5.4-nano", "gpt-5.4-mini"),
    "gpt-5-nano": ("gpt-5.4-nano", "gpt-5.4-mini"),
    "gpt-5-5-nano": ("gpt-5.4-nano", "gpt-5.4-mini"),
    "gpt-5-4-nano": ("gpt-5.4-nano", "gpt-5.4-mini"),
}


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
            input=decimal_value(item["input"]),
            cached_input=decimal_value(item["cached_input"]),
            output=decimal_value(item["output"]),
            reasoning_output=decimal_value(reasoning_raw) if reasoning_raw is not None else None,
            cache_creation_input=(
                decimal_value(item["cache_creation_input"])
                if item.get("cache_creation_input") is not None
                else None
            ),
            cache_creation_input_1h=(
                decimal_value(item["cache_creation_input_1h"])
                if item.get("cache_creation_input_1h") is not None
                else None
            ),
        )
    return parsed


@dataclass(frozen=True)
class RateCard:
    """Per-run rate resolver. Loads any local overrides exactly once."""

    api_overrides: dict[str, Rates]
    pricing_mode: str
    catalog_cards: dict[str, ModelCard] = field(default_factory=dict)
    pricing_catalog: PricingCatalog | None = None
    _cost_cache: dict[tuple, tuple[CostTotals, bool, bool]] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )
    _cache_savings_cache: dict[tuple, CostTotals] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )
    _event_cost_cache: dict[tuple, tuple[CostTotals, bool, bool]] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )
    _event_cache_savings_cache: dict[tuple, CostTotals] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )

    @classmethod
    def load(
        cls,
        path: Path | str | None,
        pricing_mode: str = "model",
        catalog: PricingCatalog | None = None,
    ) -> RateCard:
        if path is None:
            return cls(
                api_overrides={},
                pricing_mode=pricing_mode,
                catalog_cards=_catalog_cards(catalog),
                pricing_catalog=catalog,
            )
        path = path if isinstance(path, Path) else Path(path)
        try:
            raw = json.loads(path.expanduser().read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read rates file {path}: {exc}") from exc
        return cls(
            api_overrides=_parse_overrides(raw, "usd"),
            pricing_mode=pricing_mode,
            catalog_cards=_catalog_cards(catalog),
            pricing_catalog=catalog,
        )

    @classmethod
    def from_options(cls, options: RuntimeOptions) -> RateCard:
        catalog = load_pricing_catalog(
            pricing_source=options.pricing_source,
            ttl_hours=options.pricing_cache_ttl_hours,
            offline=options.offline,
        )
        return cls.load(options.rates_file, options.pricing_mode, catalog=catalog)

    def cost_for(
        self, usage: Usage, model: str, service_tier: str
    ) -> tuple[CostTotals, bool, bool]:
        normalized = normalize_model(model)
        normalized_tier = normalize_service_tier(service_tier) or service_tier
        cache_key = _cost_cache_key(usage, normalized, normalized_tier, self.pricing_mode)
        cached = self._cost_cache.get(cache_key)
        if cached is not None:
            return cached
        flat = self.pricing_mode == "flat"
        card = self._card_for(normalized)
        long_context, input_mult, output_mult = self._long_context_multipliers(usage, card, flat)
        billable_usage, ambiguous_reasoning = _billable_usage(usage)
        rates, rate_unpriced, local_override = self._resolve_usd_rates(normalized, card, flat)
        cache_rate_estimated = _cache_rate_estimated(billable_usage, rates)
        calculated = _estimate(billable_usage, rates, input_mult, output_mult)
        calculated *= service_tier_cost_multiplier(normalized, normalized_tier)
        result = (
            CostTotals(
                cost_usd=calculated,
                calculated_cost_usd=calculated,
                unpriced_events=int(rate_unpriced),
                estimated_events=int(flat or cache_rate_estimated),
                ambiguous_reasoning_events=int(ambiguous_reasoning),
                local_override_events=int(local_override),
            ),
            long_context,
            card is None and rate_unpriced,
        )
        self._cost_cache[cache_key] = result
        return result

    def _card_for(self, normalized: str) -> ModelCard | None:
        return self.catalog_cards.get(normalized) or MODELS_BY_NAME.get(normalized)

    def _long_context_multipliers(
        self, usage: Usage, card: ModelCard | None, flat: bool
    ) -> tuple[bool, Decimal, Decimal]:
        rule = card.long_context if (card and not flat) else None
        long_context = rule is not None and usage.input_tokens > rule.threshold
        if not long_context or rule is None:
            return False, Decimal("1"), Decimal("1")
        return True, decimal_value(rule.input_mult), decimal_value(rule.output_mult)

    def cache_savings_for(self, usage: Usage, model: str, service_tier: str) -> CostTotals:
        if not usage.cached_input_tokens:
            return CostTotals()
        cache_key = _cost_cache_key(
            usage,
            normalize_model(model),
            service_tier,
            self.pricing_mode,
            "cache-savings",
        )
        cached = self._cache_savings_cache.get(cache_key)
        if cached is not None:
            return cached
        uncached_usage = Usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_output_tokens=usage.reasoning_output_tokens,
            total_tokens=usage.total_tokens,
        )
        uncached_cost, _, _ = self.cost_for(uncached_usage, model, service_tier)
        actual_cost, _, _ = self.cost_for(usage, model, service_tier)
        result = CostTotals(
            cost_usd=max(ZERO, uncached_cost.cost_usd - actual_cost.cost_usd),
            calculated_cost_usd=max(
                ZERO, uncached_cost.calculated_cost_usd - actual_cost.calculated_cost_usd
            ),
            unpriced_events=max(uncached_cost.unpriced_events, actual_cost.unpriced_events),
            estimated_events=max(uncached_cost.estimated_events, actual_cost.estimated_events),
            ambiguous_reasoning_events=max(
                uncached_cost.ambiguous_reasoning_events,
                actual_cost.ambiguous_reasoning_events,
            ),
            local_override_events=max(
                uncached_cost.local_override_events, actual_cost.local_override_events
            ),
        )
        self._cache_savings_cache[cache_key] = result
        return result

    def _resolve_usd_rates(
        self, normalized: str, card: ModelCard | None, flat: bool
    ) -> tuple[Rates | None, bool, bool]:
        if flat:
            return DEFAULT_API_RATES, False, False
        if normalized in self.api_overrides:
            return self.api_overrides[normalized], False, True
        if card and card.api_rates is not None:
            return card.api_rates, False, False
        return None, True, False


def _billable_usage(usage: Usage) -> tuple[Usage, bool]:
    reasoning = usage.reasoning_output_tokens
    if not reasoning:
        return usage, False
    total_with_reasoning_in_output = usage.input_tokens + usage.output_tokens
    total_with_reasoning_separate = usage.input_tokens + usage.output_tokens + reasoning
    if usage.total_tokens == total_with_reasoning_in_output:
        return _usage_with(usage, reasoning_output_tokens=0), False
    if usage.total_tokens == total_with_reasoning_separate:
        return usage, False
    return _usage_with(usage, reasoning_output_tokens=0), True


def _usage_with(usage: Usage, **changes: int) -> Usage:
    values = {
        "input_tokens": usage.input_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "cache_creation_input_1h_tokens": usage.cache_creation_input_1h_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_output_tokens": usage.reasoning_output_tokens,
        "total_tokens": usage.total_tokens,
    }
    values.update(changes)
    return Usage(**values)


def _cost_cache_key(
    usage: Usage,
    model: str,
    service_tier: str,
    pricing_mode: str,
    *extra: str,
) -> tuple:
    return (
        usage.input_tokens,
        usage.cache_creation_input_tokens,
        usage.cache_read_input_tokens,
        usage.cache_creation_input_1h_tokens,
        usage.output_tokens,
        usage.reasoning_output_tokens,
        usage.total_tokens,
        model,
        service_tier,
        pricing_mode,
        *extra,
    )


def _estimate(
    usage: Usage, rates: Rates | None, input_mult: Decimal, output_mult: Decimal
) -> Decimal:
    if rates is None:
        return ZERO
    return (
        decimal_value(usage.uncached_input_tokens) * rates.input * input_mult
        + decimal_value(usage.cache_read_input_tokens) * rates.cached_input * input_mult
        + decimal_value(usage.cache_creation_input_tokens)
        * (rates.cache_creation_input if rates.cache_creation_input is not None else rates.input)
        * input_mult
        + decimal_value(usage.cache_creation_input_1h_tokens)
        * (
            rates.cache_creation_input_1h
            if rates.cache_creation_input_1h is not None
            else rates.input
        )
        * input_mult
        + decimal_value(usage.output_tokens) * rates.output * output_mult
        + decimal_value(usage.reasoning_output_tokens)
        * rates.effective_reasoning_output
        * output_mult
    ) / Decimal("1000000")


def _cache_rate_estimated(usage: Usage, rates: Rates | None) -> bool:
    if rates is None:
        return False
    return bool(
        (usage.cache_creation_input_tokens and rates.cache_creation_input is None)
        or (usage.cache_creation_input_1h_tokens and rates.cache_creation_input_1h is None)
    )


def _catalog_cards(catalog: PricingCatalog | None) -> dict[str, ModelCard]:
    if catalog is None:
        return {}
    cards: dict[str, ModelCard] = {}
    for key, model in catalog.models.items():
        normalized = normalize_model(key)
        embedded = MODELS_BY_NAME.get(normalized)
        cards.setdefault(
            normalized,
            ModelCard(
                name=normalized,
                api_rates=model.api_rates or (embedded.api_rates if embedded else None),
                long_context=model.long_context or (embedded.long_context if embedded else None),
            ),
        )
    return cards


def load_rate_card(options: RuntimeOptions) -> RateCard:
    """Load the active rate card, including the cached/live catalog when configured."""
    return RateCard.from_options(options)


def available_model_names(include_cached_catalog: bool = True) -> set[str]:
    names = set(MODELS_BY_NAME)
    if include_cached_catalog:
        catalog = load_cached_catalog()
        names.update(normalize_model(name) for name in available_catalog_models(catalog))
    return names


def pricing_catalog_status(card: RateCard) -> dict[str, object]:
    catalog = card.pricing_catalog
    if catalog is None:
        return {"source": "embedded", "models": 0, "age_hours": None, "warnings": []}
    return {
        "source": catalog.source,
        "models": catalog.model_count,
        "age_hours": catalog_age_hours(catalog),
        "path": str(catalog.path) if catalog.path else "",
        "warnings": list(catalog.warnings),
    }


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
