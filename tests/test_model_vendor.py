"""Test the model_vendor lookup and its glyph mapping."""

from __future__ import annotations

import pytest

from caliper.pricing import (
    KNOWN_MODEL_VENDORS,
    MODEL_CARDS,
    VENDOR_ANTHROPIC,
    VENDOR_ANYSPHERE,
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
        ("composer-1", VENDOR_ANYSPHERE),
        ("cursor-small", VENDOR_ANYSPHERE),
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
