from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from caliper.aggregation import aggregate_total, event_cost
from caliper.config import build_options
from caliper.evidence import evidence_dimensions
from caliper.models import (
    VENDOR_CLAUDE_CODE,
    VENDOR_CURSOR,
    VENDOR_OPENAI_CODEX,
    LoadResult,
    ThreadMeta,
    Usage,
    UsageEvent,
)
from caliper.pricing import RateCard
from caliper.render import pricing_status, pricing_warnings


def _event(
    *,
    vendor: str = VENDOR_OPENAI_CODEX,
    model: str = "gpt-5.5",
    tier: str = "standard",
    usage: Usage | None = None,
) -> UsageEvent:
    return UsageEvent(
        timestamp=dt.datetime(2026, 5, 13, 12, 0, tzinfo=dt.UTC),
        path=Path("/tmp/session.jsonl"),
        session_id="session-1",
        usage=usage or Usage(input_tokens=1000, output_tokens=100, total_tokens=1100),
        model=model,
        service_tier=tier,
        tier_source="logged",
        thread=ThreadMeta(cwd="/tmp/project", git_sha="abc123"),
        model_source="test",
        usage_source="test",
        vendor=vendor,
    )


def _result(*events: UsageEvent) -> LoadResult:
    return LoadResult(
        events=list(events),
        duplicates=0,
        tier_sources={"logged": len(events)},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )


def _options(tmp_path: Path):
    return build_options(
        days=1,
        until="2026-05-14T00:00:00Z",
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "config.toml",
    )


def test_non_codex_vendor_prices_cost_usd(tmp_path: Path) -> None:
    usage = Usage(
        input_tokens=1000,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=500,
        output_tokens=100,
        total_tokens=1100,
    )
    result = _result(_event(vendor=VENDOR_CLAUDE_CODE, model="claude-sonnet-4.6", usage=usage))

    total = aggregate_total(result, _options(tmp_path), rate_card=RateCard.load(None, "model"))

    assert total.costs.cost_usd == Decimal("0.0033")
    assert total.costs.calculated_cost_usd == Decimal("0.0033")
    assert total.costs.unpriced_events == 0
    assert pricing_status(total) == "exact"
    pricing_dimension = {item.name: item for item in evidence_dimensions(result, total)}["pricing"]
    assert pricing_dimension.grade == "exact"


def test_same_openai_model_costs_same_across_tools() -> None:
    card = RateCard.load(None, "model")
    codex_event = _event(vendor=VENDOR_OPENAI_CODEX, model="gpt-5.5")
    cursor_event = _event(vendor=VENDOR_CURSOR, model="gpt-5.5")

    codex_cost, _, _ = event_cost(card, codex_event)
    cursor_cost, _, _ = event_cost(card, cursor_event)

    assert codex_cost.cost_usd > 0
    assert cursor_cost.cost_usd == codex_cost.cost_usd
    assert cursor_cost.calculated_cost_usd == codex_cost.calculated_cost_usd
    assert cursor_cost.unpriced_events == 0


def test_cursor_unknown_model_is_partial_due_missing_usd_rate(
    tmp_path: Path,
) -> None:
    result = _result(_event(vendor=VENDOR_CURSOR, model="cursor-auto"))

    total = aggregate_total(result, _options(tmp_path), rate_card=RateCard.load(None, "model"))

    assert total.costs.unpriced_events == 1
    assert total.unknown_model_events == 1
    assert pricing_status(total) == "partial"
    warnings = pricing_warnings(total)
    assert any("USD rate" in warning for warning in warnings)


def test_codex_max_usd_rate_is_exact(tmp_path: Path) -> None:
    result = _result(_event(vendor=VENDOR_OPENAI_CODEX, model="gpt-5.1-codex-max"))

    total = aggregate_total(result, _options(tmp_path), rate_card=RateCard.load(None, "model"))

    assert total.costs.cost_usd == Decimal("0.00225")
    assert total.costs.unpriced_events == 0
    assert pricing_status(total) == "exact"
    assert pricing_warnings(total) == []


def test_fast_mode_applies_codex_multiplier_for_supported_models() -> None:
    card = RateCard.load(None, "model")
    standard_cost, _, _ = event_cost(card, _event(model="gpt-5.5", tier="standard"))
    fast_cost, _, _ = event_cost(card, _event(model="gpt-5.5", tier="fast"))

    assert fast_cost.cost_usd == standard_cost.cost_usd * Decimal("2.5")
    assert fast_cost.calculated_cost_usd == standard_cost.calculated_cost_usd * Decimal("2.5")
