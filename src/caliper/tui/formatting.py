"""Display formatting for TUI numeric cells."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from caliper.models import decimal_value

VENDOR_LABELS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "anysphere": "Anysphere",
    "cursor": "Cursor",
    "aider": "Aider",
    "unknown": "unknown",
}


def format_cost_usd(value: Any) -> str:
    return _format_decimal(value, places=2, prefix="$")


def format_cost_usd_cell(item: Any) -> str:
    cost_usd = _cost_value(item, "cost_usd")
    unpriced = _unpriced_events(item, "unpriced_events")
    if unpriced and cost_usd == 0:
        return "n/a"
    return format_cost_usd(cost_usd)


def format_vendor_label(value: str) -> str:
    return VENDOR_LABELS.get(value, value)


def _cost_value(item: Any, *names: str) -> Decimal:
    costs = getattr(item, "costs", item)
    for name in names:
        if hasattr(costs, name):
            return decimal_value(getattr(costs, name))
    return Decimal("0")


def _unpriced_events(item: Any, *names: str) -> int:
    costs = getattr(item, "costs", item)
    return max(int(getattr(costs, name, 0) or 0) for name in names)


def _format_decimal(value: Any, *, places: int, prefix: str = "") -> str:
    quantum = Decimal("1").scaleb(-places)
    amount = decimal_value(value).quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{prefix}{amount:,.{places}f}"
