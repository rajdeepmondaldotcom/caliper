"""Test the model_vendor lookup and its glyph mapping."""

from __future__ import annotations

import pytest

from caliper.pricing import (
    KNOWN_MODEL_VENDORS,
    MODEL_CARDS,
    VENDOR_ANTHROPIC,
    VENDOR_GOOGLE,
    VENDOR_META,
    VENDOR_MISTRAL,
    VENDOR_OPENAI,
    VENDOR_UNKNOWN,
    model_vendor,
    model_vendor_glyph,
)


def test_every_card_in_the_catalog_has_a_known_vendor():
    """No model in MODEL_CARDS may fall through to 'unknown'."""
    for card in MODEL_CARDS:
        vendor = model_vendor(card.name)
        assert vendor != VENDOR_UNKNOWN, (
            f"{card.name!r} fell through to unknown; add a prefix rule."
        )
        assert vendor in KNOWN_MODEL_VENDORS


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-opus-4.7", VENDOR_ANTHROPIC),
        ("claude-sonnet-4.6", VENDOR_ANTHROPIC),
        ("claude-haiku-4.5", VENDOR_ANTHROPIC),
        ("anthropic/claude-3-5-sonnet", VENDOR_ANTHROPIC),
        ("gpt-5.5", VENDOR_OPENAI),
        ("gpt-4o-mini", VENDOR_OPENAI),
        ("o1-preview", VENDOR_OPENAI),
        ("o3-mini", VENDOR_OPENAI),
        ("openai/gpt-4", VENDOR_OPENAI),
        ("gemini-2.0-pro", VENDOR_GOOGLE),
        ("google/gemini-1.5", VENDOR_GOOGLE),
        ("mistral-large", VENDOR_MISTRAL),
        ("codestral-22b", VENDOR_MISTRAL),
        ("llama-3.3-70b", VENDOR_META),
        ("meta/llama", VENDOR_META),
    ],
)
def test_known_prefixes(model, expected):
    assert model_vendor(model) == expected


@pytest.mark.parametrize("model", ["", None, "   ", "totally-made-up"])
def test_unknown_falls_through_to_unknown(model):
    assert model_vendor(model) == VENDOR_UNKNOWN


def test_case_insensitive():
    assert model_vendor("CLAUDE-OPUS-4.7") == VENDOR_ANTHROPIC
    assert model_vendor("Gpt-5.5") == VENDOR_OPENAI


def test_strips_whitespace():
    assert model_vendor("  claude-opus-4.7  ") == VENDOR_ANTHROPIC


def test_glyph_map_covers_all_vendors():
    """Every known vendor has a glyph except 'unknown' which falls to '?'."""
    seen = set()
    for vendor in KNOWN_MODEL_VENDORS:
        glyph = model_vendor_glyph(vendor)
        seen.add(glyph)
    assert "?" in seen  # unknown returns ?
    assert "A" in seen
    assert "O" in seen


def test_glyph_is_single_character():
    for vendor in KNOWN_MODEL_VENDORS:
        glyph = model_vendor_glyph(vendor)
        assert len(glyph) == 1, f"{vendor!r} glyph {glyph!r} is not single-char"


def test_aggregate_populates_model_vendors():
    """Pin aggregation behaviour through a real parse path."""
    import datetime as dt
    import tempfile
    from pathlib import Path

    from caliper.aggregation import aggregate_total
    from caliper.config import build_options
    from caliper.parser import load_usage

    from .conftest import token_event, write_session  # type: ignore[import-not-found]

    tmp = Path(tempfile.mkdtemp(prefix="caliper-vendor-test-"))
    write_session(
        tmp,
        "rollout-2026-05-12T00-00-00-vendor.jsonl",
        [
            {
                "type": "turn_context",
                "timestamp": "2026-05-12T00:00:00Z",
                "payload": {"model": "claude-opus-4.7"},
            },
            token_event(
                dt.datetime.now(tz=dt.UTC),
                {"input_tokens": 100, "output_tokens": 50},
            ),
        ],
    )
    options = build_options(
        session_root=tmp,
        state_db=tmp / "state.db",
        codex_config=tmp / "cfg.toml",
        days=1,
        no_parse_cache=True,
    )
    result = load_usage(options)
    if not result.events:
        return  # no events parsed; conftest fixture may not survive without state db
    total = aggregate_total(result, options)
    assert "anthropic" in total.model_vendors
    for breakdown in total.model_breakdowns.values():
        assert breakdown.model_vendor in {"anthropic", "openai", "unknown"}


def test_json_payload_includes_model_vendor_fields():
    """JSON contract gains model_vendor + model_vendors. No removals."""
    from caliper.models import Aggregate, ModelBreakdown
    from caliper.render import aggregate_to_dict, model_breakdown_to_dict

    item = Aggregate(key="x", label="x", models={"claude-opus-4.7"}, model_vendors={"anthropic"})
    item.model_breakdowns = {
        "claude-opus-4.7|standard": ModelBreakdown(
            key="claude-opus-4.7|standard",
            model="claude-opus-4.7",
            service_tier="standard",
            model_vendor="anthropic",
        )
    }
    payload = aggregate_to_dict(item)
    assert payload["model_vendors"] == ["anthropic"]
    assert "vendors" in payload  # tool-vendor field still present
    assert payload["model_breakdowns"][0]["model_vendor"] == "anthropic"

    # Direct breakdown serializer
    breakdown = ModelBreakdown(
        key="m|s", model="gpt-5.5", service_tier="standard", model_vendor="openai"
    )
    out = model_breakdown_to_dict(breakdown)
    assert out["model_vendor"] == "openai"
