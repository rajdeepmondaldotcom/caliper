from __future__ import annotations

from dataclasses import dataclass

HEURISTICS_VERSION = "1"


@dataclass(frozen=True)
class RuleInfo:
    rule_id: str
    title: str
    explanation: str


RULES: dict[str, RuleInfo] = {
    "premium-short-context": RuleInfo(
        "premium-short-context",
        "Premium model used on a short prompt",
        (
            "Flags premium models when the input context is small enough that "
            "a cheaper model may be viable."
        ),
    ),
    "fast-tier-low-output": RuleInfo(
        "fast-tier-low-output",
        "Fast tier used on a low-output event",
        "Flags fast-tier usage with small outputs as a possible standard-tier candidate.",
    ),
    "opus-no-reasoning": RuleInfo(
        "opus-no-reasoning",
        "Opus event without reasoning tokens",
        "Flags Opus-class calls when the event did not record reasoning tokens.",
    ),
}
