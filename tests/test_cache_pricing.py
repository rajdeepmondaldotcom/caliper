from __future__ import annotations

from decimal import Decimal

from caliper.models import Rates, Usage
from caliper.pricing import estimate_event_cost


def test_legacy_cached_input_still_maps_to_cache_read() -> None:
    usage = Usage(input_tokens=1000, cached_input_tokens=400, output_tokens=10, total_tokens=1010)

    assert usage.cache_read_input_tokens == 400
    assert usage.cached_input_tokens == 400
    assert usage.uncached_input_tokens == 600


def test_claude_cache_creation_and_read_rates_are_distinct() -> None:
    usage = Usage(
        input_tokens=350,
        cache_creation_input_tokens=50,
        cache_read_input_tokens=200,
        output_tokens=25,
        total_tokens=375,
    )

    cost, _long_context, unknown = estimate_event_cost(
        usage, "claude-sonnet-4.6", "standard", "model", None
    )

    assert unknown is False
    assert cost.api_dollars == Decimal("0.0009225")
    assert cost.credit_unpriced_events == 1


def test_cache_write_without_specific_rate_is_marked_estimated() -> None:
    usage = Usage(
        input_tokens=100,
        cache_creation_input_tokens=50,
        output_tokens=10,
        total_tokens=160,
    )

    cost, _long_context, unknown = estimate_event_cost(usage, "gpt-5.5", "standard", "model", None)

    assert unknown is False
    assert cost.estimated_events == 1
    assert cost.api_dollars > 0


def test_rates_accept_optional_cache_creation_slots() -> None:
    rates = Rates(
        input=3,
        cached_input=0.3,
        output=15,
        cache_creation_input=3.75,
        cache_creation_input_1h=6,
    )

    assert rates.cache_creation_input == Decimal("3.75")
    assert rates.cache_creation_input_1h == Decimal("6")
