"""Voice rules for Caliper's user-facing copy.

The rules themselves live in :mod:`caliper.persona`. These tests pin
both the rule set and the way each rule fires.
"""

from __future__ import annotations

import pytest

from caliper.persona import (
    VoiceLintError,
    VoiceViolation,
    voice_lint,
    voice_lint_strict,
)


def test_empty_string_has_no_violations():
    assert voice_lint("") == []


def test_clean_sentence_passes():
    assert voice_lint("Last 7 days. 1,234 cost_usd. $42.") == []


def test_em_dash_is_blocked():
    issues = voice_lint("Caliper — the cost ledger")
    assert any(issue.rule == "no-em-dash" for issue in issues)


def test_semicolon_is_blocked():
    issues = voice_lint("It's not speed; it's clarity.")
    assert any(issue.rule == "no-semicolon" for issue in issues)


def test_double_bang_is_blocked():
    issues = voice_lint("Ship it!!")
    assert any(issue.rule == "no-double-bang" for issue in issues)


def test_trailing_ellipsis_is_blocked():
    issues = voice_lint("Loading sessions...")
    assert any(issue.rule == "no-ellipsis" for issue in issues)


def test_solo_ellipsis_is_allowed():
    # Rich progress glyph and similar one-glyph statuses survive.
    assert voice_lint("…") == []
    assert voice_lint("...") == []


@pytest.mark.parametrize(
    "phrase",
    [
        "Leveraging cutting-edge insights",
        "World-class platform with seamless onboarding",
        "We will leverage best practices",
        "Industry-leading robust solution",
        "Game-changing next-gen flow",
        "Powerful tool that lets you operationalize",
        "Move the needle with quick wins",
    ],
)
def test_banned_phrases_are_caught(phrase):
    issues = voice_lint(phrase)
    rules = {issue.rule for issue in issues}
    assert "banned-term" in rules


def test_violations_are_specific():
    issues = voice_lint("Powerful, robust, seamless.")
    fragments = {issue.fragment for issue in issues}
    assert {"powerful", "robust", "seamless"}.issubset(fragments)


def test_strict_mode_raises():
    with pytest.raises(VoiceLintError) as caught:
        voice_lint_strict("Powerful platform.")
    assert any(v.rule == "banned-term" for v in caught.value.violations)


def test_strict_mode_silent_on_clean_copy():
    voice_lint_strict("Decision: ship the smaller version on Tuesday.")


def test_violation_is_hashable_and_repr_safe():
    violation = VoiceViolation(rule="x", fragment="y", detail="z")
    assert hash(violation) == hash(violation)
    assert "x" in repr(violation)
