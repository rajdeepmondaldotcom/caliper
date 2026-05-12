from __future__ import annotations

from codex_meter.models import Usage
from codex_meter.pricing import (
    estimate_event_cost,
    normalize_model,
    normalize_service_tier,
)


def test_model_and_tier_normalization() -> None:
    assert normalize_model("gpt-5.5-2026-04-23") == "gpt-5.5"
    assert normalize_model("GPT-5.4-Mini") == "gpt-5.4-mini"
    assert normalize_model("gpt-5-3-codex-preview") == "gpt-5.3-codex"
    assert normalize_model("gpt-5.3-codex-spark") == "gpt-5.3-codex-spark"
    assert normalize_service_tier("priority") == "fast"
    assert normalize_service_tier("regular") == "standard"


def test_estimate_event_cost_applies_cached_input_and_fast_multiplier() -> None:
    usage = Usage(
        input_tokens=1_000_000,
        cached_input_tokens=500_000,
        output_tokens=100_000,
        reasoning_output_tokens=25_000,
        total_tokens=1_100_000,
    )

    cost, long_context, unknown_model = estimate_event_cost(usage, "gpt-5.5", "fast", "model", None)

    # gpt-5.5 long-context: input ×2, output ×1.5; reasoning billed at output rate.
    # api ($/M): uncached 500K × 5 × 2 + cached 500K × 0.5 × 2 +
    #            output 100K × 30 × 1.5 + reasoning 25K × 30 × 1.5 = 11.125
    # credits: uncached 500K × 125 × 2 + cached 500K × 12.5 × 2 +
    #          output 100K × 750 × 1.5 + reasoning 25K × 750 × 1.5 = 278.125
    # fast 2.5× → 695.3125
    assert long_context is True
    assert unknown_model is False
    assert round(cost.api_dollars, 3) == 11.125
    assert round(cost.standard_credits, 3) == 278.125
    assert round(cost.adjusted_credits, 4) == 695.3125


def test_reasoning_tokens_contribute_at_output_rate_when_unspecified() -> None:
    """Reasoning tokens default to billing at the output rate."""
    bare = Usage(input_tokens=1000, output_tokens=0, total_tokens=1000)
    with_reasoning = Usage(
        input_tokens=1000, output_tokens=0, reasoning_output_tokens=1000, total_tokens=2000
    )
    bare_cost, _, _ = estimate_event_cost(bare, "gpt-5.5", "standard", "model", None)
    reasoning_cost, _, _ = estimate_event_cost(with_reasoning, "gpt-5.5", "standard", "model", None)
    # 1000 reasoning tokens × $30/M = $0.03 added to API dollars.
    assert round(reasoning_cost.api_dollars - bare_cost.api_dollars, 6) == round(
        1000 * 30 / 1_000_000, 6
    )


def test_long_context_rule_lives_on_model_card() -> None:
    """gpt-5.5 has a long-context rule, gpt-5.4 does not."""
    from codex_meter.pricing import MODELS_BY_NAME

    assert MODELS_BY_NAME["gpt-5.5"].long_context is not None
    assert MODELS_BY_NAME["gpt-5.5"].long_context.threshold == 272_000
    assert MODELS_BY_NAME["gpt-5.5"].long_context.input_mult == 2.0
    assert MODELS_BY_NAME["gpt-5.5"].long_context.output_mult == 1.5
    assert MODELS_BY_NAME["gpt-5.4"].long_context is None


def test_unknown_model_uses_fallback_without_marking_flat_mode_unknown() -> None:
    usage = Usage(input_tokens=10_000, output_tokens=1_000, total_tokens=11_000)

    _cost, _long_context, unknown_model = estimate_event_cost(
        usage, "future-model", "standard", "model", None
    )
    assert unknown_model is True

    _cost, _long_context, unknown_model = estimate_event_cost(
        usage, "future-model", "standard", "flat", None
    )
    assert unknown_model is False


def test_long_context_rule_is_limited_to_gpt_55() -> None:
    usage = Usage(input_tokens=300_000, output_tokens=10_000, total_tokens=310_000)

    _cost_55, long_55, _ = estimate_event_cost(usage, "gpt-5.5", "standard", "model", None)
    _cost_54, long_54, _ = estimate_event_cost(usage, "gpt-5.4", "standard", "model", None)

    assert long_55 is True
    assert long_54 is False


def test_codex_max_has_api_and_credit_rates() -> None:
    """gpt-5.1-codex-max has API and credit rates — must not be marked unknown."""
    usage = Usage(input_tokens=1000, output_tokens=100, total_tokens=1100)
    cost, _long_context, unknown_model = estimate_event_cost(
        usage, "gpt-5.1-codex-max", "standard", "model", None
    )
    assert unknown_model is False
    assert round(cost.api_dollars, 6) == round((1000 * 1.25 + 100 * 10.0) / 1_000_000, 6)
    assert round(cost.adjusted_credits, 6) == round((1000 * 31.25 + 100 * 250.0) / 1_000_000, 6)
