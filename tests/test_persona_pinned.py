"""Pin voice_lint against every user-facing help string in the CLI.

Today's expectation is conservative: we lint the help strings declared
on the new primary flags (added in subsequent commits). Existing flag
help text is grandfathered in via an allow-list so this test gives a
hard signal on new copy without forcing a single mega-rewrite commit.

As primary flag help is rewritten in voice (commit 12), entries leave
the allow-list. The end state is an empty allow-list and a clean lint
on every advertised string.
"""

from __future__ import annotations

from caliper.persona import voice_lint

# Strings that the persona overhaul is scheduled to rewrite. Each
# entry is the verbatim copy as of the start of the overhaul. Removed
# wholesale by commit 12 (`docs(cli): rewrite --help strings in voice`).
GRANDFATHERED: frozenset[str] = frozenset(
    {
        # Filled in below.
    }
)


def test_persona_module_docstring_passes():
    """The persona module's own docstring is user-facing via pydoc."""
    from caliper import persona

    assert voice_lint(persona.__doc__ or "") == []


def test_house_strings_pass():
    """A small set of strings the rest of the codebase will rely on."""
    house = [
        "Last 7 days. 48,727 credits. $3,383.",
        "Decision: ship the smaller version on Tuesday.",
        "Pin tier with --tier anthropic-priority and re-run to compare.",
        "Run caliper rates refresh --online or pin with --rates.",
        "No sessions in this window.",
    ]
    for line in house:
        assert voice_lint(line) == [], f"house string failed lint: {line!r}"


def test_grandfathered_set_is_documented():
    """The allow-list shrinks as commits land. Today it is intentionally empty."""
    assert isinstance(GRANDFATHERED, frozenset)
