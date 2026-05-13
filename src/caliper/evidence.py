from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from caliper.models import Aggregate, LoadResult, ParserIssue, VendorParseStats

GRADE_EXACT = "exact"
GRADE_ESTIMATED = "estimated"
GRADE_PARTIAL = "partial"
GRADE_UNSUPPORTED = "unsupported"
GRADE_ORDER = {
    GRADE_EXACT: 0,
    GRADE_ESTIMATED: 1,
    GRADE_PARTIAL: 2,
    GRADE_UNSUPPORTED: 3,
}


@dataclass(frozen=True)
class EvidenceDimension:
    name: str
    grade: str
    events: int
    reasons: tuple[str, ...] = ()

    def to_record(self) -> dict[str, object]:
        return {
            "name": self.name,
            "grade": self.grade,
            "events": self.events,
            "reasons": list(self.reasons),
        }


def parser_issue_warning(issue: ParserIssue) -> str:
    examples = "; ".join(issue.examples)
    suffix = f" (examples: {examples})" if examples else ""
    return f"{issue.message}: {issue.count:,} files{suffix}"


def warnings_from_parser_issues(issues: list[ParserIssue]) -> list[str]:
    return [parser_issue_warning(issue) for issue in issues if issue.severity != "info"]


def evidence_metadata(result: LoadResult, total: Aggregate) -> dict[str, object]:
    dimensions = evidence_dimensions(result, total)
    return {
        "overall": worst_grade([dimension.grade for dimension in dimensions]),
        "dimensions": [dimension.to_record() for dimension in dimensions],
        "vendor_coverage": vendor_coverage_records(result),
        "parser_issues": [issue.to_record() for issue in result.parser_issues],
    }


def evidence_dimensions(result: LoadResult, total: Aggregate) -> list[EvidenceDimension]:
    return [
        usage_evidence(result),
        model_evidence(total),
        tier_evidence(total),
        pricing_evidence(total),
        project_evidence(result),
        git_evidence(result),
    ]


def usage_evidence(result: LoadResult) -> EvidenceDimension:
    events = len(result.events)
    unsupported = sum(stats.unsupported_files for stats in result.vendor_stats.values())
    sources = Counter(event.usage_source or "unknown" for event in result.events)
    reasons: list[str] = []
    if unsupported:
        reasons.append(f"{unsupported:,} discovered files have no supported usage records")
    if sources.get("unknown"):
        reasons.append(f"{sources['unknown']:,} events have unknown usage provenance")
    if unsupported and not events:
        grade = GRADE_UNSUPPORTED
    elif unsupported:
        grade = GRADE_PARTIAL
    elif sources.get("unknown"):
        grade = GRADE_ESTIMATED
    else:
        grade = GRADE_EXACT
    return EvidenceDimension("usage", grade, events, tuple(reasons))


def model_evidence(total: Aggregate) -> EvidenceDimension:
    reasons: list[str] = []
    if total.unknown_model_events:
        reasons.append(f"{total.unknown_model_events:,} events used models outside the rate card")
    if total.fallback_model_events:
        reasons.append(f"{total.fallback_model_events:,} events used the configured default model")
    if total.unknown_model_events:
        grade = GRADE_PARTIAL
    elif total.fallback_model_events:
        grade = GRADE_ESTIMATED
    else:
        grade = GRADE_EXACT
    return EvidenceDimension("model", grade, total.totals.events, tuple(reasons))


def tier_evidence(total: Aggregate) -> EvidenceDimension:
    if total.unknown_tier_events:
        return EvidenceDimension(
            "tier",
            GRADE_ESTIMATED,
            total.totals.events,
            (f"{total.unknown_tier_events:,} events used inferred service tiers",),
        )
    return EvidenceDimension("tier", GRADE_EXACT, total.totals.events)


def pricing_evidence(total: Aggregate) -> EvidenceDimension:
    reasons: list[str] = []
    if total.costs.api_unpriced_events:
        reasons.append(f"{total.costs.api_unpriced_events:,} events have no API-dollar rate")
    if total.costs.credit_unpriced_events:
        reasons.append(f"{total.costs.credit_unpriced_events:,} events have no Codex credit rate")
    if total.costs.estimated_events:
        reasons.append(f"{total.costs.estimated_events:,} events used estimated rate logic")
    if total.costs.ambiguous_reasoning_events:
        reasons.append(
            f"{total.costs.ambiguous_reasoning_events:,} events had ambiguous reasoning tokens"
        )
    if total.costs.unpriced_events:
        grade = GRADE_PARTIAL
    elif total.costs.estimated_events or total.costs.ambiguous_reasoning_events:
        grade = GRADE_ESTIMATED
    else:
        grade = GRADE_EXACT
    return EvidenceDimension("pricing", grade, total.totals.events, tuple(reasons))


def project_evidence(result: LoadResult) -> EvidenceDimension:
    events = len(result.events)
    missing = sum(1 for event in result.events if not event.thread.cwd)
    if missing:
        return EvidenceDimension(
            "project",
            GRADE_PARTIAL,
            events,
            (f"{missing:,} events have no project path",),
        )
    return EvidenceDimension("project", GRADE_EXACT, events)


def git_evidence(result: LoadResult) -> EvidenceDimension:
    events = len(result.events)
    missing = sum(1 for event in result.events if not event.thread.git_sha)
    if missing == events and events:
        return EvidenceDimension(
            "git_attribution",
            GRADE_UNSUPPORTED,
            events,
            ("no loaded events include a recorded git SHA",),
        )
    if missing:
        return EvidenceDimension(
            "git_attribution",
            GRADE_PARTIAL,
            events,
            (f"{missing:,} events have no recorded git SHA",),
        )
    return EvidenceDimension("git_attribution", GRADE_EXACT, events)


def vendor_coverage_records(result: LoadResult) -> list[dict[str, object]]:
    stats = dict(result.vendor_stats)
    event_counts = Counter(event.vendor or "unknown" for event in result.events)
    issue_counts = Counter(issue.vendor for issue in result.parser_issues)
    vendors = sorted(set(stats) | set(event_counts) | set(issue_counts))
    records = []
    for vendor in vendors:
        item = stats.get(vendor) or VendorParseStats(vendor=vendor)
        event_count = event_counts.get(vendor, item.event_count)
        warning_count = issue_counts.get(vendor, item.warning_count)
        records.append(
            {
                **item.to_record(),
                "event_count": event_count,
                "warning_count": warning_count,
                "coverage": _coverage(item.discovered_files, item.files_with_events),
                "confidence": _vendor_confidence(item, warning_count),
            }
        )
    return records


def evidence_rows(result: LoadResult, total: Aggregate) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "section": "dimension",
            "name": dimension.name,
            "grade": dimension.grade,
            "events": dimension.events,
            "reason": "; ".join(dimension.reasons),
        }
        for dimension in evidence_dimensions(result, total)
    ]
    rows.extend(
        {
            "section": "vendor",
            "name": record["vendor"],
            "grade": record["confidence"],
            "events": record["event_count"],
            "reason": (
                f"{record['files_with_events']}/{record['discovered_files']} files with events; "
                f"{record['unsupported_files']} unsupported"
            ),
        }
        for record in vendor_coverage_records(result)
    )
    return rows


def worst_grade(grades: list[str]) -> str:
    if not grades:
        return GRADE_EXACT
    return max(grades, key=lambda grade: GRADE_ORDER.get(grade, 0))


def _coverage(discovered: int, with_events: int) -> float:
    return with_events / discovered if discovered else 0.0


def _vendor_confidence(stats: VendorParseStats, warning_count: int) -> str:
    if stats.discovered_files and stats.files_with_events == 0 and stats.unsupported_files:
        return GRADE_UNSUPPORTED
    if stats.unsupported_files or warning_count:
        return GRADE_PARTIAL
    if stats.discovered_files and stats.files_with_events == 0:
        return GRADE_UNSUPPORTED
    return GRADE_EXACT
