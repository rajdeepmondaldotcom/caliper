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


def _options(tmp_path: Path, *, compact: bool = False):
    now = dt.datetime(2026, 5, 13, 12, 0, tzinfo=dt.UTC)
    return build_options(
        days=1,
        until=now.isoformat(),
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "missing.toml",
        compact=compact,
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
        credit_samples=samples or [],
        warnings=["parser warning"],
    )


def _aggregate(label: str = "row") -> Aggregate:
    agg = Aggregate(key=label, label=label)
    agg.add_event(
        _event(),
        CostTotals(api_dollars="1.23", standard_credits="10", adjusted_credits="25"),
        CostTotals(api_dollars="0.50", standard_credits="1", adjusted_credits="2"),
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
    assert "Standard-mode baseline" in text
    assert "Cache savings:" in text
    assert "Service-tier sources: logged=1" in text
    assert "Plan types: free" in text


def test_pricing_status_and_warning_branches() -> None:
    agg = Aggregate(key="warn", label="warn")
    agg.costs = CostTotals(
        api_unpriced_events=1,
        credit_unpriced_events=2,
        estimated_events=3,
        ambiguous_reasoning_events=4,
        vendor_reported_events=5,
    )
    agg.unknown_model_events = 6
    agg.unknown_tier_events = 7
    agg.fallback_model_events = 8

    warnings = render_module.pricing_warnings(agg)

    assert render_module.pricing_status(agg) == "partial"
    assert any("API-dollar" in warning for warning in warnings)
    assert any("Codex credit" in warning for warning in warnings)
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

    breakdown = ModelBreakdown(key="m", model="m", service_tier="standard")
    breakdown.costs = CostTotals(api_unpriced_events=1)
    assert render_module.model_breakdown_pricing_status(breakdown) == "partial"
    breakdown.costs = CostTotals(vendor_reported_events=1)
    assert render_module.model_breakdown_pricing_status(breakdown) == "vendor-reported"


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
    assert payload["caliper"]["schema_version"] == 1

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
        credits=123,
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
        mb.costs.api_dollars = Decimal(str(dollars))
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
        vendor="cursor",
        message="Cursor files have no per-event token counts",
        severity="warn",
        kind="cursor-missing-tokens",
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
        mb.costs.api_dollars = Decimal(str(dollars))
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
    mb.costs.api_dollars = Decimal("10")
    mb.totals = TokenTotals()
    item = Aggregate(key="x", label="x", models={"claude-opus-4.7"})
    item.model_breakdowns = {"claude-opus-4.7": mb}
    item.costs = CostTotals()
    out = compact_models_oneline(item)
    assert "\n" not in out
    assert "Anthropic" not in out
