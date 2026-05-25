"""Single source of truth for the ranked "fixable" recommendation set.

Every surface that answers *"what should I do about cost"* — ``caliper
recommend``, ``caliper exec``, and the dashboard verdict/advisor slot —
derives its numbers from :func:`select_recommendations`. That guarantees
the headline dollar figure, the recommendation count, and the named top
fix agree across surfaces, so a number quoted from one command reconciles
with every other.

The spine is the quantified inefficiency engine (:func:`caliper.efficiency.run_audit`
+ :func:`caliper.efficiency.rank_recommendations`). The arbitrage engine
(``caliper advise`` / ``caliper whatif``) is a complementary model/tier
re-pricing sweep and is intentionally *not* merged here — its events carry
no stable ids, so folding it in would double-count dollars. ``advise`` is
labelled as the separate lens it is and cross-references this canonical set.

Key invariant: ``fixable_shown_usd`` is the sum of exactly the ``ranked``
items that a surface displays, so "Fixable $X across N" reconciles by
construction rather than by coincidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from caliper.efficiency import (
    rank_recommendations,
    run_audit,
    total_savings_usd,
)
from caliper.models import Finding, LoadResult, Recommendation, RuntimeOptions
from caliper.pricing import RateCard

# A finding must reach this confidence to survive ``--strict``.
STRICT_CONFIDENCE = "high"


@dataclass(frozen=True)
class RecommendationSet:
    """The reconciled recommendation surface for one window.

    - ``ranked`` — the top-N items a surface shows.
    - ``findings`` — the full deduped finding list (for ``caliper audit``).
    - ``fixable_shown_usd`` — sum of ``ranked`` only; this is the number a
      surface should print as "Fixable $X across N".
    - ``total_savings_usd`` — sum of *every* finding; kept for machine
      consumers and the "full audit" reference line.
    """

    ranked: list[Recommendation]
    findings: list[Finding]
    fixable_shown_usd: Decimal
    monthly_shown_usd: Decimal
    total_savings_usd: Decimal
    top: int

    @property
    def shown_count(self) -> int:
        return len(self.ranked)

    @property
    def total_findings(self) -> int:
        return len(self.findings)

    @property
    def top_fix(self) -> Recommendation | None:
        return self.ranked[0] if self.ranked else None


def select_recommendations(
    result: LoadResult,
    options: RuntimeOptions,
    card: RateCard,
    *,
    top: int = 5,
    strict: bool = False,
) -> RecommendationSet:
    """Run the audit and return the canonical ranked recommendation set.

    ``strict`` keeps only high-confidence findings (the same intent as
    ``caliper advise --strict``), applied to the *same* engine so a strict
    view is always a subset of the default one — never a different answer.
    """
    findings = run_audit(result, options, card)
    if strict:
        findings = [f for f in findings if f.confidence == STRICT_CONFIDENCE]
    ranked = rank_recommendations(findings, top=top)
    fixable_shown = sum((r.impact_usd_exact for r in ranked), Decimal("0"))
    monthly_shown = sum((r.monthly_projected_savings_usd for r in ranked), Decimal("0"))
    return RecommendationSet(
        ranked=ranked,
        findings=findings,
        fixable_shown_usd=fixable_shown,
        monthly_shown_usd=monthly_shown,
        total_savings_usd=total_savings_usd(findings),
        top=top,
    )


__all__ = ["RecommendationSet", "STRICT_CONFIDENCE", "select_recommendations"]
