"""Caliper's house voice: Calm, Accountable Clarity.

Single source of truth for the persona rules that govern every
user-visible string Caliper prints. Lifted from
`docs/persona-overhaul/01-plan.md` and `VOICE_PROFILE_RAJDEEP.md`.

The :func:`voice_lint` function returns a list of human-readable
violations for a given string. Callers can run it in tests, in CI, or
inline before shipping copy. An empty list means the string passes.

Rules are intentionally short. Each one has a one-line rationale so a
maintainer reading a failure knows what to change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Words and phrases that signal fog, hype, or buzzword fatigue. Sourced
# verbatim from the voice profile (Q25). The list is conservative on
# purpose: a few false positives are acceptable, false negatives are not.
_BANNED_TERMS: tuple[str, ...] = (
    # Performative announcement speak
    "thrilled to announce",
    "excited to share",
    "delighted to share",
    "proud to announce",
    "humbled to share",
    "beyond excited",
    "i'm stoked",
    "feeling blessed",
    # Vague journey framing
    "the journey",
    "next chapter",
    "next adventure",
    "next era",
    "next level",
    "level up",
    "glow up",
    "living my purpose",
    # Buzzword verbs that hide work
    "leverage",
    "leverages",
    "leveraging",
    "leveraged",
    "utilize",
    "utilizes",
    "utilizing",
    "operationalize",
    "spearhead",
    "evangelize",
    "synergize",
    "future-proof",
    "industrialize",
    "right-size",
    "course-correct",
    # Buzzword nouns
    "synergies",
    "thought leadership",
    "best practices",
    "playbook",
    "north star",
    "stakeholder management",
    "change management",
    "operating model",
    # Empty adjectives
    "cutting-edge",
    "world-class",
    "best-in-class",
    "groundbreaking",
    "game-changing",
    "revolutionary",
    "next-gen",
    "state-of-the-art",
    "industry-leading",
    "award-winning",
    "unparalleled",
    "frictionless",
    "mission-critical",
    "enterprise-grade",
    "powerful",
    "seamless",
    "robust",
    # "Trust me" authority signals
    "thought leader",
    "rockstar",
    "ninja",
    "trailblazer",
    # Fake precision
    "at scale",
    "hockey stick",
    "10x",
    "needle-moving",
    "move the needle",
    "low-hanging fruit",
    "quick wins",
    # Tech buzzwords as perfume
    "ai-powered",
    "ml-driven",
    "intelligent automation",
    "hyperautomation",
    "data lakehouse",
    "single source of truth",
    "real-time insights",
    "personalization at scale",
    "shift-left",
    # Clichés that replace thinking
    "in today's world",
    "now more than ever",
    "at the end of the day",
    "in this space",
    "let that sink in",
    "this is a game changer",
    "the new normal",
    "unprecedented times",
    "fail fast",
    "fail forward",
    "lean in",
    "trust the process",
    # Hype words
    "revolutionize",
    "reinvent",
    "disrupt the",
    "reshape the industry",
    "paradigm shift",
    "step-function",
)

# Allowed exceptions. Caliper's own marketing line uses "Calm,
# Accountable Clarity" verbatim and that is by design. Add narrow
# exceptions, never broad ones.
_BANNED_EXCEPTIONS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class VoiceViolation:
    """A single voice rule that the input string broke."""

    rule: str
    fragment: str
    detail: str


def voice_lint(text: str) -> list[VoiceViolation]:
    """Return zero or more :class:`VoiceViolation` records for ``text``.

    Empty list means the string passes. The rules implemented today:

    1. **No em dashes.** Hard rule from Q22. Use periods, dashes, or
       parentheses instead.
    2. **No semicolons.** Hard rule from Q22. Split into two sentences.
    3. **No banned hype/buzzword terms.** Hard rule from Q25.
    4. **No double exclamation.** "!!" reads as theatre.
    5. **No "…" or "..." for tone.** Trailing ellipses read as
       performance (Q22). Ellipses inside ranges or as the literal Rich
       progress indicator are exempt.
    """
    if not text:
        return []
    lowered = text.lower()
    violations: list[VoiceViolation] = []

    if "—" in text:
        violations.append(
            VoiceViolation(
                rule="no-em-dash",
                fragment="—",
                detail="Em dashes break the voice. Use periods, a dash, or split the sentence.",
            )
        )
    if ";" in text:
        violations.append(
            VoiceViolation(
                rule="no-semicolon",
                fragment=";",
                detail="Semicolons invite long blended sentences. Split into two.",
            )
        )
    if "!!" in text:
        violations.append(
            VoiceViolation(
                rule="no-double-bang",
                fragment="!!",
                detail="Double exclamation reads as theatre.",
            )
        )
    has_ellipsis = bool(re.search(r"(?<!\.)\.\.\.(?!\.)", text)) or "…" in text
    if has_ellipsis and text.strip() not in {"…", "..."}:
        violations.append(
            VoiceViolation(
                rule="no-ellipsis",
                fragment="...",
                detail="Ellipses read as trailing-off. Land the sentence.",
            )
        )

    for term in _BANNED_TERMS:
        if term in _BANNED_EXCEPTIONS:
            continue
        # Match whole words/phrases case-insensitive. Allow apostrophes
        # inside the term (e.g. "i'm stoked").
        pattern = rf"(?<![a-z]){re.escape(term)}(?![a-z])"
        if re.search(pattern, lowered):
            violations.append(
                VoiceViolation(
                    rule="banned-term",
                    fragment=term,
                    detail=(
                        f"'{term}' is on the banned list. "
                        "Use a concrete verb, a number, or a constraint instead."
                    ),
                )
            )
    return violations


def voice_lint_strict(text: str) -> None:
    """Raise :class:`VoiceLintError` if ``text`` has any violations."""
    issues = voice_lint(text)
    if not issues:
        return
    summary = "\n".join(f"  - {v.rule}: '{v.fragment}' ({v.detail})" for v in issues)
    raise VoiceLintError(
        f"voice violations in:\n  {text!r}\n{summary}",
        violations=tuple(issues),
    )


class VoiceLintError(ValueError):
    """Raised when a string violates the persona rules in strict mode."""

    def __init__(self, message: str, violations: tuple[VoiceViolation, ...]) -> None:
        super().__init__(message)
        self.violations = violations


__all__ = [
    "VoiceLintError",
    "VoiceViolation",
    "voice_lint",
    "voice_lint_strict",
]
