from __future__ import annotations

from pathlib import Path

DOCS_SITE = Path("docs-site/src/content/docs")
LAUNCH_DOCS = Path("docs/launch")


def test_docs_site_install_and_budget_examples_match_live_cli() -> None:
    docs = "\n".join(path.read_text() for path in DOCS_SITE.glob("*.mdx"))

    assert "uvx --isolated --from caliper-ai caliper" in docs
    assert "daily_cost_usd" in docs
    assert "weekly_cost_usd" in docs
    assert "monthly_cost_usd" in docs

    stale_needles = [
        "uvx --from caliper-ai caliper",
        "daily_credits",
        "weekly_credits",
        "monthly_api_dollars",
        " credits",
    ]
    for needle in stale_needles:
        assert needle not in docs


def test_launch_drafts_match_current_install_and_output_language() -> None:
    docs = "\n".join(path.read_text() for path in LAUNCH_DOCS.glob("*.md"))

    assert "uvx --isolated --from caliper-ai caliper" in docs
    assert "uvx --from caliper-ai caliper" not in docs
    assert " credits" not in docs
