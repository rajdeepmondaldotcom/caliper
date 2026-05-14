from __future__ import annotations

from pathlib import Path

DOCS_SITE = Path("docs-site/src/content/docs")


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
        "48,727 credits",
        "52,691 credits",
    ]
    for needle in stale_needles:
        assert needle not in docs
