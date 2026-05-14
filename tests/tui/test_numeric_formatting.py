from __future__ import annotations

from decimal import Decimal

from caliper.models import Aggregate, CostTotals
from caliper.tui.formatting import format_cost_usd, format_cost_usd_cell


def test_cost_usd_format_from_decimal_without_float_rounding() -> None:
    assert format_cost_usd(Decimal("2147.425")) == "$2,147.43"


def test_unpriced_api_cell_is_not_rendered_as_zero_spend() -> None:
    row = Aggregate(
        key="future-model\0standard",
        label="future-model / standard",
        costs=CostTotals(cost_usd=0, unpriced_events=2),
    )

    assert format_cost_usd_cell(row) == "n/a"
