from __future__ import annotations

from decimal import Decimal

from caliper.models import Usage
from caliper.pricing import (
    estimate_event_cost,
    normalize_model,
    normalize_service_tier,
)


def test_model_and_tier_normalization() -> None:
    assert normalize_model("gpt-5.5-2026-04-23") == "gpt-5.5"
    assert normalize_model("GPT-5.4-Mini") == "gpt-5.4-mini"
    assert normalize_model("gpt-5-3-codex-preview") == "gpt-5.3-codex"
    assert normalize_model("gpt-5.3-codex-spark") == "gpt-5.3-codex-spark"
    assert normalize_model("gpt-5.5-pro") == "gpt-5.5-pro"
    assert normalize_service_tier("priority") == "fast"
    assert normalize_service_tier("regular") == "standard"


def test_estimate_event_cost_applies_cached_input_and_long_context_usd() -> None:
    usage = Usage(
        input_tokens=1_000_000,
        cached_input_tokens=500_000,
        output_tokens=100_000,
        reasoning_output_tokens=25_000,
        total_tokens=1_100_000,
    )

    cost, long_context, unknown_model = estimate_event_cost(usage, "gpt-5.5", "fast", "model", None)

    # gpt-5.5 long-context: input ×2, output ×1.5. This token shape has
    # total_tokens == input_tokens + output_tokens, so reasoning is already
    # included in output_tokens and must not be billed again.
    # USD ($/M): uncached 500K × 5 × 2 + cached 500K × 0.5 × 2 +
    #            output 100K × 30 × 1.5 = 10.00
    assert long_context is True
    assert unknown_model is False
    assert cost.cost_usd == Decimal("10.00")
    assert cost.calculated_cost_usd == Decimal("10.00")


def test_reasoning_tokens_contribute_at_output_rate_when_unspecified() -> None:
    """Reasoning tokens default to billing at the output rate."""
    bare = Usage(input_tokens=1000, output_tokens=0, total_tokens=1000)
    with_reasoning = Usage(
        input_tokens=1000, output_tokens=0, reasoning_output_tokens=1000, total_tokens=2000
    )
    bare_cost, _, _ = estimate_event_cost(bare, "gpt-5.5", "standard", "model", None)
    reasoning_cost, _, _ = estimate_event_cost(with_reasoning, "gpt-5.5", "standard", "model", None)
    # 1000 reasoning tokens × $30/M = $0.03 added to API dollars.
    assert (reasoning_cost.cost_usd - bare_cost.cost_usd).quantize(Decimal("0.000001")) == Decimal(
        "0.030000"
    )


def test_reasoning_tokens_are_not_double_counted_when_output_already_includes_them() -> None:
    without_reasoning = Usage(input_tokens=1000, output_tokens=1000, total_tokens=2000)
    with_included_reasoning = Usage(
        input_tokens=1000,
        output_tokens=1000,
        reasoning_output_tokens=500,
        total_tokens=2000,
    )

    bare_cost, _, _ = estimate_event_cost(without_reasoning, "gpt-5.5", "standard", "model", None)
    included_cost, _, _ = estimate_event_cost(
        with_included_reasoning, "gpt-5.5", "standard", "model", None
    )

    assert included_cost.cost_usd == bare_cost.cost_usd
    assert included_cost.ambiguous_reasoning_events == 0


def test_ambiguous_reasoning_shape_is_marked_and_not_double_counted() -> None:
    usage = Usage(
        input_tokens=1000,
        output_tokens=1000,
        reasoning_output_tokens=500,
        total_tokens=2300,
    )

    cost, _, _ = estimate_event_cost(usage, "gpt-5.5", "standard", "model", None)

    assert cost.cost_usd == Decimal("0.035")
    assert cost.ambiguous_reasoning_events == 1


def test_long_context_rule_lives_on_model_card() -> None:
    """Long-context rules live on model cards."""
    from caliper.pricing import MODELS_BY_NAME

    assert MODELS_BY_NAME["gpt-5.5"].long_context is not None
    assert MODELS_BY_NAME["gpt-5.5"].long_context.threshold == 272_000
    assert MODELS_BY_NAME["gpt-5.5"].long_context.input_mult == 2.0
    assert MODELS_BY_NAME["gpt-5.5"].long_context.output_mult == 1.5
    assert MODELS_BY_NAME["gpt-5.4"].long_context is not None
    assert MODELS_BY_NAME["gpt-5.4"].long_context.threshold == 272_000


def test_unknown_model_is_unpriced_without_marking_flat_mode_unknown() -> None:
    usage = Usage(input_tokens=10_000, output_tokens=1_000, total_tokens=11_000)

    cost, _long_context, unknown_model = estimate_event_cost(
        usage, "future-model", "standard", "model", None
    )
    assert unknown_model is True
    assert cost.cost_usd == Decimal("0")
    assert cost.unpriced_events == 1

    _cost, _long_context, unknown_model = estimate_event_cost(
        usage, "future-model", "standard", "flat", None
    )
    assert unknown_model is False


def test_long_context_rule_applies_to_1050k_context_models() -> None:
    usage = Usage(input_tokens=300_000, output_tokens=10_000, total_tokens=310_000)

    _cost_55, long_55, _ = estimate_event_cost(usage, "gpt-5.5", "standard", "model", None)
    _cost_54, long_54, _ = estimate_event_cost(usage, "gpt-5.4", "standard", "model", None)

    assert long_55 is True
    assert long_54 is True


def test_codex_max_has_usd_rate() -> None:
    """gpt-5.1-codex-max is USD-priced."""
    usage = Usage(input_tokens=1000, output_tokens=100, total_tokens=1100)
    cost, _long_context, unknown_model = estimate_event_cost(
        usage, "gpt-5.1-codex-max", "standard", "model", None
    )
    assert unknown_model is False
    assert cost.cost_usd == Decimal("0.00225")
    assert cost.unpriced_events == 0


def test_anthropic_cache_rate_ratios_match_published_card() -> None:
    """Cache read = 0.1x input; cache write 5min = 1.25x input; cache write 1h = 2x input."""
    from caliper.pricing import MODELS_BY_NAME

    for name in ("claude-haiku-4.5", "claude-sonnet-4.6", "claude-opus-4.7"):
        card = MODELS_BY_NAME[name]
        rates = card.api_rates
        assert rates is not None, name
        assert rates.cached_input == rates.input * Decimal("0.1"), name
        assert rates.cache_creation_input == rates.input * Decimal("1.25"), name
        assert rates.cache_creation_input_1h == rates.input * Decimal("2"), name


def test_anthropic_pricing_has_sourced_attribution() -> None:
    """Every Anthropic model card has a sourced URL in PRICING_SOURCES."""
    from caliper.pricing import PRICING_SOURCES

    names = " ".join(source.name.lower() for source in PRICING_SOURCES)
    assert "anthropic" in names
    assert "haiku" in names
    assert "sonnet" in names
    assert "opus" in names
    assert "prompt caching" in names


def test_anthropic_pricing_round_trip_for_each_card() -> None:
    """Each Anthropic card prices a realistic three-way cache split with no unknown model flag."""
    usage = Usage(
        input_tokens=1000,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=500,
        output_tokens=100,
        total_tokens=1100,
    )
    for model in ("claude-haiku-4.5", "claude-sonnet-4.6", "claude-opus-4.7"):
        cost, _long, unknown = estimate_event_cost(usage, model, "standard", "model", None)
        assert unknown is False, model
        assert cost.cost_usd > Decimal("0"), model
        assert cost.unpriced_events == 0, model
