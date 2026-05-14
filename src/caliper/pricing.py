"""Embedded Codex rate card + RateCard resolver (offline-first)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

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

DEFAULT_API_RATES = Rates(input=5.0, cached_input=0.5, output=30.0)
DEFAULT_CREDIT_RATES = Rates(input=125.0, cached_input=12.5, output=750.0)

LONG_CONTEXT_1050K = LongContextRule(
    threshold=LONG_CONTEXT_INPUT_THRESHOLD, input_mult=2.0, output_mult=1.5
)


@dataclass(frozen=True)
class ModelCard:
    """One Codex model's pricing. Missing rates are intentionally unpriced."""

    name: str
    api_rates: Rates | None
    credit_rates: Rates | None
    fast_multiplier: float = 1.0
    long_context: LongContextRule | None = None


MODEL_CARDS: tuple[ModelCard, ...] = (
    ModelCard(
        name="gpt-5.5",
        api_rates=Rates(5.0, 0.5, 30.0),
        credit_rates=Rates(125.0, 12.5, 750.0),
        fast_multiplier=2.5,
        long_context=LONG_CONTEXT_1050K,
    ),
    ModelCard(
        name="gpt-5.4",
        api_rates=Rates(2.5, 0.25, 15.0),
        credit_rates=Rates(62.5, 6.25, 375.0),
        fast_multiplier=2.0,
        long_context=LONG_CONTEXT_1050K,
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
        api_rates=Rates(1.25, 0.125, 10.0),
        credit_rates=None,
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
        credit_rates=None,
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
        credit_rates=None,
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
        credit_rates=None,
    ),
)

MODELS_BY_NAME: dict[str, ModelCard] = {card.name: card for card in MODEL_CARDS}


# Canonical labels for the entity that *makes* the model. Distinct from
# the tool vendor that wrote the log (Cursor can route to Anthropic or
# OpenAI; the tool is Cursor, the model vendor is Anthropic/OpenAI).
VENDOR_ANTHROPIC = "anthropic"
VENDOR_OPENAI = "openai"
VENDOR_ANYSPHERE = "anysphere"
VENDOR_GOOGLE = "google"
VENDOR_MISTRAL = "mistral"
VENDOR_META = "meta"
VENDOR_UNKNOWN = "unknown"

KNOWN_MODEL_VENDORS: tuple[str, ...] = (
    VENDOR_ANTHROPIC,
    VENDOR_OPENAI,
    VENDOR_ANYSPHERE,
    VENDOR_GOOGLE,
    VENDOR_MISTRAL,
    VENDOR_META,
    VENDOR_UNKNOWN,
)

# Regex-style prefix mapping. The first hit wins. Lower-case match.
_MODEL_VENDOR_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude-", VENDOR_ANTHROPIC),
    ("claude/", VENDOR_ANTHROPIC),
    ("anthropic/", VENDOR_ANTHROPIC),
    ("gpt-", VENDOR_OPENAI),
    ("o1-", VENDOR_OPENAI),
    ("o3-", VENDOR_OPENAI),
    ("o4-", VENDOR_OPENAI),
    ("o5-", VENDOR_OPENAI),
    ("openai/", VENDOR_OPENAI),
    ("text-", VENDOR_OPENAI),
    ("composer-", VENDOR_ANYSPHERE),
    ("cursor-", VENDOR_ANYSPHERE),
    ("cursor/", VENDOR_ANYSPHERE),
    ("anysphere/", VENDOR_ANYSPHERE),
    ("gemini-", VENDOR_GOOGLE),
    ("google/", VENDOR_GOOGLE),
    ("palm-", VENDOR_GOOGLE),
    ("mistral-", VENDOR_MISTRAL),
    ("mistral/", VENDOR_MISTRAL),
    ("codestral", VENDOR_MISTRAL),
    ("llama-", VENDOR_META),
    ("meta/", VENDOR_META),
)


def model_vendor(model: str | None) -> str:
    """Return the canonical vendor label for a model id.

    Lookup order:
    1. Exact match in :data:`MODELS_BY_NAME` (always derives from prefix).
    2. Prefix match against :data:`_MODEL_VENDOR_PREFIXES`.
    3. Fallback to :data:`VENDOR_UNKNOWN`.

    Case-insensitive. Empty or ``None`` returns ``unknown``.
    """
    if not model:
        return VENDOR_UNKNOWN
    lowered = str(model).strip().lower()
    if not lowered:
        return VENDOR_UNKNOWN
    for prefix, vendor in _MODEL_VENDOR_PREFIXES:
        if lowered.startswith(prefix):
            return vendor
    return VENDOR_UNKNOWN


def model_vendor_glyph(vendor: str) -> str:
    """Short single-character glyph for the dense Models screen header."""
    return {
        VENDOR_ANTHROPIC: "A",
        VENDOR_OPENAI: "O",
        VENDOR_ANYSPHERE: "C",
        VENDOR_GOOGLE: "G",
        VENDOR_MISTRAL: "M",
        VENDOR_META: "L",
    }.get(vendor, "?")


PRICING_SOURCES = [
    PricingSource(
        name="OpenAI API pricing",
        url="https://developers.openai.com/api/docs/pricing",
        checked="2026-05-13",
    ),
    PricingSource(
        name="GPT-5.5 model pricing and long-context rule",
        url="https://developers.openai.com/api/docs/models/gpt-5.5",
        checked="2026-05-13",
    ),
    PricingSource(
        name="GPT-5.4 model pricing and long-context rule",
        url="https://developers.openai.com/api/docs/models/gpt-5.4",
        checked="2026-05-13",
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
        checked="2026-05-13",
    ),
    PricingSource(
        name="GPT-5.1-Codex-Max model pricing",
        url="https://developers.openai.com/api/docs/models/gpt-5.1-codex-max",
        checked="2026-05-13",
    ),
    PricingSource(
        name="Anthropic API pricing",
        url="https://www.anthropic.com/pricing",
        checked="2026-05-13",
    ),
    PricingSource(
        name="Anthropic prompt caching (cache write 1.25x, cache read 0.1x)",
        url="https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching",
        checked="2026-05-13",
    ),
    PricingSource(
        name="Claude Haiku 4.5 model pricing",
        url="https://www.anthropic.com/claude/haiku",
        checked="2026-05-13",
    ),
    PricingSource(
        name="Claude Sonnet 4.6 model pricing",
        url="https://www.anthropic.com/claude/sonnet",
        checked="2026-05-13",
    ),
    PricingSource(
        name="Claude Opus 4.7 model pricing",
        url="https://www.anthropic.com/claude/opus",
        checked="2026-05-13",
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
    credit_overrides: dict[str, Rates]
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
        path: Path | None,
        pricing_mode: str = "model",
        catalog: PricingCatalog | None = None,
    ) -> RateCard:
        if path is None:
            return cls(
                api_overrides={},
                credit_overrides={},
                pricing_mode=pricing_mode,
                catalog_cards=_catalog_cards(catalog),
                pricing_catalog=catalog,
            )
        try:
            raw = json.loads(path.expanduser().read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read rates file {path}: {exc}") from exc
        return cls(
            api_overrides=_parse_overrides(raw, "api"),
            credit_overrides=_parse_overrides(raw, "credits"),
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
        cache_key = _cost_cache_key(usage, normalized, service_tier, self.pricing_mode)
        cached = self._cost_cache.get(cache_key)
        if cached is not None:
            return cached
        flat = self.pricing_mode == "flat"
        card = self._card_for(normalized)
        long_context, input_mult, output_mult = self._long_context_multipliers(usage, card, flat)
        billable_usage, ambiguous_reasoning = _billable_usage(usage)
        api_rates, api_unpriced, api_local = self._resolve_api_rates(normalized, card, flat)
        credit_rates, credit_unpriced, credit_local = self._resolve_credit_rates(
            normalized, card, flat
        )
        cache_rate_estimated = _cache_rate_estimated(
            billable_usage, api_rates
        ) or _cache_rate_estimated(billable_usage, credit_rates)
        standard_credits = _estimate(billable_usage, credit_rates, input_mult, output_mult)
        adjusted_credits, tier_estimated = self._adjusted_credits(
            standard_credits, service_tier, card, credit_rates
        )
        result = (
            CostTotals(
                api_dollars=_estimate(billable_usage, api_rates, input_mult, output_mult),
                standard_credits=standard_credits,
                adjusted_credits=adjusted_credits,
                api_unpriced_events=int(api_unpriced),
                credit_unpriced_events=int(credit_unpriced),
                estimated_events=int(flat or tier_estimated or cache_rate_estimated),
                ambiguous_reasoning_events=int(ambiguous_reasoning),
                local_override_events=int(api_local or credit_local),
            ),
            long_context,
            card is None and api_unpriced and credit_unpriced,
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

    def _adjusted_credits(
        self,
        standard_credits: Decimal,
        service_tier: str,
        card: ModelCard | None,
        credit_rates: Rates | None,
    ) -> tuple[Decimal, bool]:
        if service_tier != "fast" or credit_rates is None:
            return standard_credits, False
        if card is None:
            return standard_credits, True
        return standard_credits * decimal_value(card.fast_multiplier), False

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
            api_dollars=max(ZERO, uncached_cost.api_dollars - actual_cost.api_dollars),
            standard_credits=max(
                ZERO, uncached_cost.standard_credits - actual_cost.standard_credits
            ),
            adjusted_credits=max(
                ZERO, uncached_cost.adjusted_credits - actual_cost.adjusted_credits
            ),
            api_unpriced_events=max(
                uncached_cost.api_unpriced_events, actual_cost.api_unpriced_events
            ),
            credit_unpriced_events=max(
                uncached_cost.credit_unpriced_events, actual_cost.credit_unpriced_events
            ),
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

    def _resolve_api_rates(
        self, normalized: str, card: ModelCard | None, flat: bool
    ) -> tuple[Rates | None, bool, bool]:
        if flat:
            return DEFAULT_API_RATES, False, False
        if normalized in self.api_overrides:
            return self.api_overrides[normalized], False, True
        if card and card.api_rates is not None:
            return card.api_rates, False, False
        return None, True, False

    def _resolve_credit_rates(
        self, normalized: str, card: ModelCard | None, flat: bool
    ) -> tuple[Rates | None, bool, bool]:
        if flat:
            return DEFAULT_CREDIT_RATES, False, False
        if normalized in self.credit_overrides:
            return self.credit_overrides[normalized], False, True
        if card and card.credit_rates is not None:
            return card.credit_rates, False, False
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
                credit_rates=model.credit_rates or (embedded.credit_rates if embedded else None),
                fast_multiplier=embedded.fast_multiplier if embedded else 1.0,
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
