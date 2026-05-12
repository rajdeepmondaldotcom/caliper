from __future__ import annotations

import json
from pathlib import Path

from codex_meter.models import CostTotals, PricingSource, Rates

LONG_CONTEXT_INPUT_THRESHOLD = 272_000

DEFAULT_API_RATES = Rates(input=5.0, cached_input=0.5, output=30.0)
DEFAULT_CREDIT_RATES = Rates(input=125.0, cached_input=12.5, output=750.0)

MODEL_API_RATES: dict[str, Rates] = {
    "gpt-5.5": Rates(input=5.0, cached_input=0.5, output=30.0),
    "gpt-5.4": Rates(input=2.5, cached_input=0.25, output=15.0),
    "gpt-5.4-mini": Rates(input=0.75, cached_input=0.075, output=4.5),
    "gpt-5.3-codex": Rates(input=1.75, cached_input=0.175, output=14.0),
    "gpt-5.2": Rates(input=1.75, cached_input=0.175, output=14.0),
}

MODEL_CREDIT_RATES: dict[str, Rates] = {
    "gpt-5.5": Rates(input=125.0, cached_input=12.5, output=750.0),
    "gpt-5.4": Rates(input=62.5, cached_input=6.25, output=375.0),
    "gpt-5.4-mini": Rates(input=18.75, cached_input=1.875, output=113.0),
    "gpt-5.3-codex": Rates(input=43.75, cached_input=4.375, output=350.0),
    "gpt-5.2": Rates(input=43.75, cached_input=4.375, output=350.0),
    "gpt-5.1-codex-max": Rates(input=31.25, cached_input=3.125, output=250.0),
}

FAST_CREDIT_MULTIPLIERS = {
    "gpt-5.5": 2.5,
    "gpt-5.4": 2.0,
}

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
    for known in sorted(set(MODEL_API_RATES) | set(MODEL_CREDIT_RATES), key=len, reverse=True):
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


def load_rate_overrides(path: Path | None) -> tuple[dict[str, Rates], dict[str, Rates]]:
    if path is None:
        return {}, {}
    try:
        raw = json.loads(path.expanduser().read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read rates file {path}: {exc}") from exc

    def parse_rates(section: str) -> dict[str, Rates]:
        values = raw.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(f"rates file section {section!r} must be an object")
        parsed: dict[str, Rates] = {}
        for model, item in values.items():
            if not isinstance(item, dict):
                raise ValueError(f"rates for {model!r} must be an object")
            parsed[normalize_model(model)] = Rates(
                input=float(item["input"]),
                cached_input=float(item["cached_input"]),
                output=float(item["output"]),
            )
        return parsed

    return parse_rates("api"), parse_rates("credits")


def rate_for_model(
    model: str,
    card: dict[str, Rates],
    fallback: Rates,
    flat: bool,
    overrides: dict[str, Rates] | None = None,
) -> tuple[Rates, bool]:
    if flat:
        return fallback, False
    normalized = normalize_model(model)
    if overrides and normalized in overrides:
        return overrides[normalized], False
    if normalized in card:
        return card[normalized], False
    return fallback, True


def estimate_with_rates(usage: dict[str, int], rates: Rates, long_context: bool) -> float:
    input_multiplier = 2.0 if long_context else 1.0
    output_multiplier = 1.5 if long_context else 1.0
    input_tokens = int(usage.get("input_tokens") or 0)
    cached_input_tokens = int(usage.get("cached_input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    uncached_input_tokens = max(0, input_tokens - cached_input_tokens)
    return (
        uncached_input_tokens * rates.input * input_multiplier
        + cached_input_tokens * rates.cached_input * input_multiplier
        + output_tokens * rates.output * output_multiplier
    ) / 1_000_000


def estimate_event_cost(
    usage: dict[str, int],
    model: str,
    service_tier: str,
    pricing_mode: str,
    rates_file: Path | None = None,
) -> tuple[CostTotals, bool, bool]:
    api_overrides, credit_overrides = load_rate_overrides(rates_file)
    normalized_model = normalize_model(model)
    long_context = int(usage.get("input_tokens") or 0) > LONG_CONTEXT_INPUT_THRESHOLD
    flat = pricing_mode == "flat"
    api_rates, unknown_api = rate_for_model(
        normalized_model, MODEL_API_RATES, DEFAULT_API_RATES, flat, api_overrides
    )
    credit_rates, unknown_credit = rate_for_model(
        normalized_model, MODEL_CREDIT_RATES, DEFAULT_CREDIT_RATES, flat, credit_overrides
    )
    standard_credits = estimate_with_rates(usage, credit_rates, long_context)
    fast_multiplier = FAST_CREDIT_MULTIPLIERS.get(normalized_model, 1.0)
    adjusted_credits = (
        standard_credits * fast_multiplier if service_tier == "fast" else standard_credits
    )
    return (
        CostTotals(
            api_dollars=estimate_with_rates(usage, api_rates, long_context),
            standard_credits=standard_credits,
            adjusted_credits=adjusted_credits,
        ),
        long_context,
        unknown_api or unknown_credit,
    )
