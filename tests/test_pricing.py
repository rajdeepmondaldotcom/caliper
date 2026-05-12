from __future__ import annotations

from codex_meter.pricing import (
    estimate_event_cost,
    normalize_model,
    normalize_service_tier,
)


def test_model_and_tier_normalization() -> None:
    assert normalize_model("gpt-5.5-2026-04-23") == "gpt-5.5"
    assert normalize_model("GPT-5.4-Mini") == "gpt-5.4-mini"
    assert normalize_model("gpt-5-3-codex-preview") == "gpt-5.3-codex"
    assert normalize_service_tier("priority") == "fast"
    assert normalize_service_tier("regular") == "standard"


def test_estimate_event_cost_applies_cached_input_and_fast_multiplier() -> None:
    usage = {
        "input_tokens": 1_000_000,
        "cached_input_tokens": 500_000,
        "output_tokens": 100_000,
        "reasoning_output_tokens": 25_000,
        "total_tokens": 1_100_000,
    }

    cost, long_context, unknown_model = estimate_event_cost(usage, "gpt-5.5", "fast", "model", None)

    assert long_context is True
    assert unknown_model is False
    assert round(cost.api_dollars, 2) == 10.00
    assert round(cost.standard_credits, 2) == 250.00
    assert round(cost.adjusted_credits, 2) == 625.00


def test_unknown_model_uses_fallback_without_marking_flat_mode_unknown() -> None:
    usage = {
        "input_tokens": 10_000,
        "cached_input_tokens": 0,
        "output_tokens": 1_000,
        "total_tokens": 11_000,
    }

    _cost, _long_context, unknown_model = estimate_event_cost(
        usage, "future-model", "standard", "model", None
    )
    assert unknown_model is True

    _cost, _long_context, unknown_model = estimate_event_cost(
        usage, "future-model", "standard", "flat", None
    )
    assert unknown_model is False
