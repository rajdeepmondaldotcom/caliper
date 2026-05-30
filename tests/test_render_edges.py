from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

from caliper import render as render_module
from caliper.aggregation import aggregate_total
from caliper.config import build_options
from caliper.models import (
    Aggregate,
    CostTotals,
    LoadResult,
    ModelBreakdown,
    RateLimitSample,
    ThreadMeta,
    Usage,
    UsageEvent,
)
from caliper.pricing import RateCard


def _options(tmp_path: Path, *, compact: bool = False, width: int | None = None):
    now = dt.datetime(2026, 5, 13, 12, 0, tzinfo=dt.UTC)
    return build_options(
        days=1,
        until=now.isoformat(),
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "missing.toml",
        compact=compact,
        width=width,
    )


def _event(
    *,
    model: str = "gpt-5.5",
    tier: str = "fast",
    plan_type: str = "free",
    vendor: str = "openai-codex",
    model_source: str = "turn_context",
) -> UsageEvent:
    return UsageEvent(
        timestamp=dt.datetime(2026, 5, 13, 11, 30, tzinfo=dt.UTC),
        path=Path("/tmp/session.jsonl"),
        session_id="session-1",
        usage=Usage(
            input_tokens=1000,
            cached_input_tokens=500,
            output_tokens=100,
            total_tokens=1100,
        ),
        model=model,
        service_tier=tier,
        tier_source="logged",
        thread=ThreadMeta(cwd="/tmp/project", title="Private prompt title"),
        model_source=model_source,
        plan_type=plan_type,
        vendor=vendor,
    )


def _load_result(*events: UsageEvent, samples: list[RateLimitSample] | None = None) -> LoadResult:
    return LoadResult(
        events=list(events),
        duplicates=2,
        tier_sources={"logged": len(events)},
        plan_types={event.plan_type for event in events if event.plan_type},
        rate_limit_samples=samples or [],
        warnings=["parser warning"],
    )


def _aggregate(label: str = "row") -> Aggregate:
    agg = Aggregate(key=label, label=label)
    agg.add_event(
        _event(),
        CostTotals(cost_usd="1.23"),
        CostTotals(cost_usd="0.50"),
        long_context=False,
        unknown_model=False,
        unknown_tier=False,
    )
    return agg


def test_render_table_footer_and_warning_paths(tmp_path: Path) -> None:
    options = _options(tmp_path, compact=True)
    result = _load_result(_event(plan_type="free"))
    total = aggregate_total(result, options, rate_card=RateCard.load(None, "model"))

    text = render_module.render_table(
        result,
        options,
        [total],
        "Surface",
        rate_card=RateCard.load(None, "model"),
    )

    assert "Surface" in text
    assert "Vendors: openai-codex" in text
    assert "parser warning" in text
    assert "Subscription:" in text
    assert "Cache discount:" in text
    assert "Service-tier sources: logged=1" in text
    assert "Plan types: free" in text


def test_render_table_names_non_codex_data_source(tmp_path: Path) -> None:
    options = _options(tmp_path, compact=True)
    result = _load_result(_event(vendor="claude-code"))
    total = aggregate_total(result, options, rate_card=RateCard.load(None, "model"))

    text = render_module.render_table(
        result,
        options,
        [total],
        "Surface",
        rate_card=RateCard.load(None, "model"),
    )

    assert "Data source: Claude Code local logs" in text
    assert "Session root:" not in text


def test_human_table_marks_unsupported_pricing_as_na(tmp_path: Path) -> None:
    options = _options(tmp_path, width=120)
    event = _event(model="unknown-model", model_source="unknown")
    unsupported = Aggregate(key="unsupported", label="unsupported")
    unsupported.add_event(
        event,
        CostTotals(cost_usd="0", calculated_cost_usd="0", unpriced_events=1),
        CostTotals(cost_usd="0"),
        long_context=False,
        unknown_model=True,
        unknown_tier=False,
    )

    text = render_module.render_table(
        _load_result(event),
        options,
        [unsupported],
        "Surface",
        rate_card=RateCard.load(None, "model"),
        total=unsupported,
    )

    assert "n/a" in text
    # The per-category warning wall is collapsed into one materiality-aware
    # evidence line; the per-category detail still ships in the JSON envelope.
    assert "unpriced" in text
    assert "partial" in text


def test_human_table_preserves_true_zero_cost(tmp_path: Path) -> None:
    options = _options(tmp_path, width=120)
    event = _event()
    zero = Aggregate(key="zero", label="zero")
    zero.add_event(
        event,
        CostTotals(cost_usd="0", calculated_cost_usd="0"),
        CostTotals(cost_usd="0"),
        long_context=False,
        unknown_model=False,
        unknown_tier=False,
    )

    text = render_module.render_table(
        _load_result(event),
        options,
        [zero],
        "Surface",
        rate_card=RateCard.load(None, "model"),
        total=zero,
    )

    assert "$0.00" in text
    assert "n/a" not in text


def test_narrow_table_uses_scan_friendly_columns(tmp_path: Path) -> None:
    options = _options(tmp_path, width=80)
    event = _event(model="gpt-supercalifragilisticexpialidocious-model-with-extra-tail")
    total = aggregate_total(_load_result(event), options, rate_card=RateCard.load(None, "model"))

    text = render_module.render_table(
        _load_result(event),
        options,
        [total],
        "Surface",
        rate_card=RateCard.load(None, "model"),
        total=total,
    )

    assert "Tokens" in text
    assert "Pricing" in text
    assert "Reported $" not in text
    assert "supercalifragilisticexpialidocious\n" not in text
    assert "$0..." not in text
    assert "$0…" not in text


def test_pricing_status_and_warning_branches() -> None:
    agg = Aggregate(key="warn", label="warn")
    agg.costs = CostTotals(
        unpriced_events=2,
        estimated_events=3,
        ambiguous_reasoning_events=4,
    )
    agg.unknown_model_events = 6
    agg.unknown_tier_events = 7
    agg.fallback_model_events = 8

    warnings = render_module.pricing_warnings(agg)

    assert render_module.pricing_status(agg) == "partial"
    assert any("USD rate" in warning for warning in warnings)
    assert any("no known rate card" in warning for warning in warnings)
    assert any("inferred service tiers" in warning for warning in warnings)
    assert any("estimate pricing" in warning for warning in warnings)
    assert any("ambiguous reasoning" in warning for warning in warnings)
    assert any("default model" in warning for warning in warnings)

    estimated = Aggregate(key="estimated", label="estimated")
    estimated.costs = CostTotals(estimated_events=1)
    assert render_module.pricing_status(estimated) == "estimated"

    vendor = Aggregate(key="vendor", label="vendor")
    vendor.costs = CostTotals(vendor_reported_events=1)
    assert render_module.pricing_status(vendor) == "vendor-reported"

    mixed_vendor = Aggregate(key="mixed-vendor", label="mixed vendor")
    mixed_vendor.costs = CostTotals(vendor_reported_events=1, unpriced_events=2)
    assert render_module.pricing_status(mixed_vendor) == "partial"

    breakdown = ModelBreakdown(key="m", model="m", service_tier="standard")
    breakdown.costs = CostTotals(unpriced_events=1)
    assert render_module.model_breakdown_pricing_status(breakdown) == "partial"
    breakdown.costs = CostTotals(vendor_reported_events=1)
    assert render_module.model_breakdown_pricing_status(breakdown) == "vendor-reported"
    breakdown.costs = CostTotals(vendor_reported_events=1, unpriced_events=2)
    assert render_module.model_breakdown_pricing_status(breakdown) == "partial"


def test_render_dispatch_and_markdown_totals(tmp_path: Path, capsys) -> None:
    options = _options(tmp_path)
    result = _load_result(_event())
    row = _aggregate("visible|row")

    markdown = render_module.render_markdown([row], show_prompts=False)
    assert "visible\\|row" in markdown
    assert "**Total**" in markdown

    for fmt in ("json", "csv", "markdown", "table"):
        output = tmp_path / f"report.{fmt}"
        render_module.render(result, options, [row], "daily", fmt, output)
        assert output.read_text()

    payload = json.loads((tmp_path / "report.json").read_text())
    assert payload["caliper"]["schema_version"] == 2

    render_module.write_output("stdout text", None)
    assert "stdout text" in capsys.readouterr().out


def test_limits_rendering_and_reset_epoch_edges(tmp_path: Path) -> None:
    now = dt.datetime.now(tz=dt.UTC)
    sample = RateLimitSample(
        timestamp=now,
        path=Path("/tmp/session.jsonl"),
        session_id="session",
        plan_type="pro",
        limit_id="codex",
        primary_used_percent=None,
        primary_window_minutes=300,
        primary_resets_at="not-an-epoch",
        secondary_used_percent=91.0,
        secondary_window_minutes=10080,
        secondary_resets_at=now.timestamp() - 10,
    )
    empty_result = _load_result()
    compact_result = _load_result(samples=[sample])

    assert "No rate-limit samples" in render_module.render_limits_table(
        empty_result, _options(tmp_path)
    )
    compact = render_module.render_limits_table(compact_result, _options(tmp_path, compact=True))
    assert "primary=None%/300m reset=not-an-epoch" in compact

    assert render_module._reset_epoch(None) == "-"
    assert render_module._reset_epoch("") == "-"
    assert render_module._reset_epoch("not-an-epoch") == "not-an-epoch"
    assert render_module._reset_epoch(now.timestamp() - 1) == "now"
    assert "h" in render_module._reset_epoch(time.time() + 3700)
    assert render_module._percent(None) == "-"


def test_short_model_strips_vendor_prefix():
    from caliper.render import short_model

    assert short_model("claude-sonnet-4.6") == "sonnet-4.6"
    assert short_model("claude-opus-4.7") == "opus-4.7"
    assert short_model("openai-foo") == "foo"
    assert short_model("gpt-5.5") == "gpt-5.5"  # GPT-N stays
    assert short_model("mistral-medium") == "mistral-medium"


def test_compact_models_returns_dash_for_empty():
    from caliper.models import Aggregate
    from caliper.render import compact_models

    item = Aggregate(key="empty", label="empty")
    assert compact_models(item) == "-"


def test_compact_models_ranks_by_spend_when_breakdowns_present():
    from decimal import Decimal

    from caliper.models import Aggregate, CostTotals, ModelBreakdown, TokenTotals
    from caliper.render import compact_models

    def _breakdown(model: str, dollars: float) -> ModelBreakdown:
        mb = ModelBreakdown(key=f"{model}|standard", model=model, service_tier="standard")
        mb.costs.cost_usd = Decimal(str(dollars))
        mb.totals = TokenTotals()
        return mb

    item = Aggregate(key="x", label="x", models={"a", "b", "c", "d"})
    item.model_breakdowns = {
        "claude-opus-4.7": _breakdown("claude-opus-4.7", 10.0),
        "gpt-5.5": _breakdown("gpt-5.5", 50.0),
        "claude-haiku-4.5": _breakdown("claude-haiku-4.5", 5.0),
        "claude-sonnet-4.6": _breakdown("claude-sonnet-4.6", 30.0),
    }
    item.costs = CostTotals()
    rendered = compact_models(item, limit=3)
    # gpt-5.5 has highest spend; expect it first
    assert rendered.startswith("gpt-5.5 ·")
    assert "+1" in rendered  # one model truncated


def test_parser_issue_warning_no_longer_dumps_paths():
    from caliper.evidence import parser_issue_warning
    from caliper.models import ParserIssue

    issue = ParserIssue(
        vendor="claude-code",
        message="Claude Code files have no per-event token counts",
        severity="warn",
        kind="claude-missing-tokens",
        count=1477,
        examples=("/very/long/path/1", "/very/long/path/2"),
    )
    out = parser_issue_warning(issue)
    assert "1,477 files" in out
    assert "caliper doctor" in out
    assert "/very/long/path/1" not in out


def test_compact_models_includes_vendor_chip_when_breakdowns_present():
    from decimal import Decimal

    from caliper.models import Aggregate, CostTotals, ModelBreakdown, TokenTotals
    from caliper.render import compact_models, vendor_chip

    def _breakdown(model: str, vendor: str, dollars: float) -> ModelBreakdown:
        mb = ModelBreakdown(
            key=f"{model}|standard",
            model=model,
            service_tier="standard",
            model_vendor=vendor,
        )
        mb.costs.cost_usd = Decimal(str(dollars))
        mb.totals = TokenTotals()
        return mb

    item = Aggregate(key="x", label="x", models={"a", "b"})
    item.model_breakdowns = {
        "claude-opus-4.7": _breakdown("claude-opus-4.7", "anthropic", 50.0),
        "gpt-5.5": _breakdown("gpt-5.5", "openai", 30.0),
    }
    item.costs = CostTotals()
    rendered = compact_models(item)
    assert "[dim]Anthropic · OpenAI[/dim]" in rendered
    assert vendor_chip(item) == "Anthropic · OpenAI"


def test_vendor_chip_empty_for_blank_row():
    from caliper.models import Aggregate
    from caliper.render import vendor_chip

    assert vendor_chip(Aggregate(key="x", label="x")) == ""


def test_compact_models_oneline_drops_chip():
    from decimal import Decimal

    from caliper.models import Aggregate, CostTotals, ModelBreakdown, TokenTotals
    from caliper.render import compact_models_oneline

    mb = ModelBreakdown(
        key="m|standard",
        model="claude-opus-4.7",
        service_tier="standard",
        model_vendor="anthropic",
    )
    mb.costs.cost_usd = Decimal("10")
    mb.totals = TokenTotals()
    item = Aggregate(key="x", label="x", models={"claude-opus-4.7"})
    item.model_breakdowns = {"claude-opus-4.7": mb}
    item.costs = CostTotals()
    out = compact_models_oneline(item)
    assert "\n" not in out
    assert "Anthropic" not in out
