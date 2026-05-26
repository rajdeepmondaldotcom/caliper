"""Trust-aware agent and skill attribution.

The functions in this module never inspect prompt text or tool inputs. They
work from structural metadata already normalized onto ``UsageEvent``:
session id, path shape, thread agent metadata, tool names, and explicit skill
names when a source exposes them.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from caliper.aggregation import event_cost
from caliper.analysis.session_shape import (
    CATEGORY_DIAGNOSTIC,
    CATEGORY_EXECUTION,
    CATEGORY_EXPLORATION,
    CATEGORY_MIXED,
    classify_session,
)
from caliper.models import Finding, LoadResult, RuntimeOptions, UsageEvent, decimal_string
from caliper.pricing import RateCard

SOURCE_USER = "user"
SOURCE_OVERHEAD = "overhead"
SOURCE_UNKNOWN = "unknown"
SOURCE_DIRECT = "direct"

EVIDENCE_EXACT = "exact"
EVIDENCE_ESTIMATED = "estimated"
EVIDENCE_PARTIAL = "partial"
EVIDENCE_UNSUPPORTED = "unsupported"

OVERHEAD_AGENT_PREFIXES = (
    "acompact-",
    "aprompt_suggestion-",
    "aside_question-",
)

OVERHEAD_WARN_SHARE = 0.15
RUNAWAY_MIN_ROWS = 5
SKILL_MIN_INVOCATIONS = 5
MIN_FINDING_IMPACT_USD = Decimal("0.10")


@dataclass
class AgentAttribution:
    agent_id: str
    source_category: str
    evidence_status: str
    reason: str
    role: str = ""
    nickname: str = ""
    kind: str = "direct-session"
    cost_usd: Decimal = Decimal("0")
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    events: int = 0
    tool_calls: int = 0
    sessions: set[str] = field(default_factory=set)
    projects: set[str] = field(default_factory=set)
    models: set[str] = field(default_factory=set)
    first_seen: dt.datetime | None = None
    last_seen: dt.datetime | None = None

    def add_event(self, event: UsageEvent, cost: Decimal) -> None:
        self.cost_usd += cost
        self.total_tokens += event.usage.total_tokens
        self.input_tokens += event.usage.input_tokens
        self.output_tokens += event.usage.output_tokens
        self.events += 1
        if event.turn_facts is not None:
            self.tool_calls += event.turn_facts.tool_use_count
        if event.session_id:
            self.sessions.add(event.session_id)
        if event.thread.cwd:
            self.projects.add(event.thread.cwd)
        if event.model:
            self.models.add(event.model)
        if self.first_seen is None or event.timestamp < self.first_seen:
            self.first_seen = event.timestamp
        if self.last_seen is None or event.timestamp > self.last_seen:
            self.last_seen = event.timestamp

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    def to_record(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "source_category": self.source_category,
            "evidence_status": self.evidence_status,
            "reason": self.reason,
            "kind": self.kind,
            "role": self.role,
            "nickname": self.nickname,
            "cost_usd": float(self.cost_usd),
            "cost_usd_exact": decimal_string(self.cost_usd),
            "total_tokens": self.total_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "events": self.events,
            "tool_calls": self.tool_calls,
            "sessions": self.session_count,
            "project_count": len(self.projects),
            "models": sorted(self.models),
            "first_seen": self.first_seen.isoformat() if self.first_seen else "",
            "last_seen": self.last_seen.isoformat() if self.last_seen else "",
        }


@dataclass
class SkillAttribution:
    name: str
    evidence_status: str
    attribution_method: str
    cost_usd: Decimal = Decimal("0")
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    invocation_count: int = 0
    events: int = 0
    event_keys: set[str] = field(default_factory=set)
    invocation_costs: list[Decimal] = field(default_factory=list)
    sessions: set[str] = field(default_factory=set)
    projects: set[str] = field(default_factory=set)
    models: set[str] = field(default_factory=set)
    first_seen: dt.datetime | None = None
    last_seen: dt.datetime | None = None

    def add_event(self, event: UsageEvent, cost_share: Decimal, token_divisor: int) -> None:
        divisor = max(token_divisor, 1)
        event_key = _event_key(event)
        self.cost_usd += cost_share
        self.invocation_costs.append(cost_share)
        self.total_tokens += event.usage.total_tokens // divisor
        self.input_tokens += event.usage.input_tokens // divisor
        self.output_tokens += event.usage.output_tokens // divisor
        self.invocation_count += 1
        if event_key not in self.event_keys:
            self.event_keys.add(event_key)
            self.events += 1
        if event.session_id:
            self.sessions.add(event.session_id)
        if event.thread.cwd:
            self.projects.add(event.thread.cwd)
        if event.model:
            self.models.add(event.model)
        if self.first_seen is None or event.timestamp < self.first_seen:
            self.first_seen = event.timestamp
        if self.last_seen is None or event.timestamp > self.last_seen:
            self.last_seen = event.timestamp

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    @property
    def median_cost_per_invocation(self) -> Decimal:
        if not self.invocation_costs:
            return Decimal("0")
        ordered = sorted(self.invocation_costs)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / Decimal("2")

    def to_record(self) -> dict[str, object]:
        return {
            "name": self.name,
            "evidence_status": self.evidence_status,
            "attribution_method": self.attribution_method,
            "estimated_cost_usd": float(self.cost_usd),
            "estimated_cost_usd_exact": decimal_string(self.cost_usd),
            "median_cost_per_invocation_usd": float(self.median_cost_per_invocation),
            "median_cost_per_invocation_usd_exact": decimal_string(self.median_cost_per_invocation),
            "total_tokens": self.total_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "invocations": self.invocation_count,
            "events": self.events,
            "sessions": self.session_count,
            "project_count": len(self.projects),
            "models": sorted(self.models),
            "first_seen": self.first_seen.isoformat() if self.first_seen else "",
            "last_seen": self.last_seen.isoformat() if self.last_seen else "",
        }


def build_agent_attributions(result: LoadResult, rate_card: RateCard) -> list[AgentAttribution]:
    rows: dict[str, AgentAttribution] = {}
    for event in result.events:
        identity = _agent_identity(event)
        row = rows.setdefault(
            identity["agent_id"],
            AgentAttribution(
                agent_id=identity["agent_id"],
                source_category=identity["source_category"],
                evidence_status=identity["evidence_status"],
                reason=identity["reason"],
                role=event.thread.agent_role,
                nickname=event.thread.agent_nickname,
                kind=identity["kind"],
            ),
        )
        cost, _, _ = event_cost(rate_card, event)
        row.add_event(event, cost.cost_usd)
    return sorted(
        rows.values(),
        key=lambda row: (-row.cost_usd, row.source_category, row.agent_id),
    )


def build_skill_attributions(result: LoadResult, rate_card: RateCard) -> list[SkillAttribution]:
    rows: dict[tuple[str, str], SkillAttribution] = {}
    for event in result.events:
        labels, evidence, method = _skill_labels_for_event(event)
        if not labels:
            continue
        cost, _, _ = event_cost(rate_card, event)
        divisor = len(labels)
        cost_share = cost.cost_usd / Decimal(divisor)
        for label in labels:
            key = (label, method)
            row = rows.setdefault(
                key,
                SkillAttribution(
                    name=label,
                    evidence_status=evidence,
                    attribution_method=method,
                ),
            )
            row.add_event(event, cost_share, divisor)
    return sorted(rows.values(), key=lambda row: (-row.cost_usd, row.name))


def agent_summary(rows: list[AgentAttribution]) -> dict[str, object]:
    total = sum((row.cost_usd for row in rows), Decimal("0"))
    overhead = sum(
        (row.cost_usd for row in rows if row.source_category == SOURCE_OVERHEAD),
        Decimal("0"),
    )
    user = sum(
        (row.cost_usd for row in rows if row.source_category == SOURCE_USER),
        Decimal("0"),
    )
    unknown = sum(
        (row.cost_usd for row in rows if row.source_category == SOURCE_UNKNOWN),
        Decimal("0"),
    )
    direct = sum(
        (row.cost_usd for row in rows if row.source_category == SOURCE_DIRECT),
        Decimal("0"),
    )
    return {
        "total_cost_usd_exact": decimal_string(total),
        "user_cost_usd_exact": decimal_string(user),
        "overhead_cost_usd_exact": decimal_string(overhead),
        "unknown_cost_usd_exact": decimal_string(unknown),
        "direct_cost_usd_exact": decimal_string(direct),
        "overhead_share": float(overhead / total) if total else 0.0,
        "rows": len(rows),
        "evidence_status": _combined_evidence_status([row.evidence_status for row in rows]),
    }


def skill_summary(rows: list[SkillAttribution], result: LoadResult) -> dict[str, object]:
    covered_events = {event_key for row in rows for event_key in row.event_keys}
    covered = len(covered_events)
    total_events = len(result.events)
    total = sum((row.cost_usd for row in rows), Decimal("0"))
    return {
        "estimated_cost_usd_exact": decimal_string(total),
        "covered_events": covered,
        "total_events": total_events,
        "coverage": covered / total_events if total_events else 0.0,
        "rows": len(rows),
        "evidence_status": _combined_evidence_status([row.evidence_status for row in rows]),
    }


def attribution_findings(
    agent_rows: list[AgentAttribution],
    skill_rows: list[SkillAttribution],
    options: RuntimeOptions,
) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_overhead_tax_findings(agent_rows, options))
    findings.extend(_runaway_agent_findings(agent_rows, options))
    findings.extend(_skill_outlier_findings(skill_rows, options))
    return sorted(findings, key=lambda item: -item.impact_usd_exact)


def _agent_identity(event: UsageEvent) -> dict[str, str]:
    session_id = event.session_id or event.path.stem
    candidates = [session_id, event.path.stem]
    normalized = [_normalize_agent_id(value) for value in candidates if value]
    if any(_is_overhead_id(value) for value in normalized):
        agent_id = next(value for value in normalized if _is_overhead_id(value))
        return {
            "agent_id": agent_id,
            "source_category": SOURCE_OVERHEAD,
            "evidence_status": EVIDENCE_EXACT,
            "reason": "known background agent prefix",
            "kind": "agent",
        }
    if event.thread.agent_role or event.thread.agent_nickname:
        agent_id = event.thread.agent_nickname or event.thread.agent_role or session_id
        return {
            "agent_id": agent_id,
            "source_category": SOURCE_USER,
            "evidence_status": EVIDENCE_EXACT,
            "reason": "logged agent metadata",
            "kind": "agent",
        }
    if event.path.stem.startswith("agent-"):
        return {
            "agent_id": _normalize_agent_id(event.path.stem),
            "source_category": SOURCE_UNKNOWN,
            "evidence_status": EVIDENCE_PARTIAL,
            "reason": "agent file pattern without role metadata",
            "kind": "agent",
        }
    return {
        "agent_id": f"direct:{session_id}",
        "source_category": SOURCE_DIRECT,
        "evidence_status": EVIDENCE_PARTIAL,
        "reason": "direct session fallback; no explicit agent metadata",
        "kind": "direct-session",
    }


def _normalize_agent_id(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("agent-"):
        normalized = normalized[6:]
    return normalized


def _is_overhead_id(value: str) -> bool:
    return any(value.startswith(prefix) for prefix in OVERHEAD_AGENT_PREFIXES)


def _skill_labels_for_event(event: UsageEvent) -> tuple[tuple[str, ...], str, str]:
    facts = event.turn_facts
    if facts is None:
        return (), EVIDENCE_UNSUPPORTED, "unsupported"
    if facts.skill_names:
        return facts.skill_names, EVIDENCE_ESTIMATED, "explicit-skill-turn"
    if facts.tool_names:
        category = classify_session(Counter(facts.tool_names))
        label = {
            CATEGORY_EXPLORATION: "workflow:exploration",
            CATEGORY_EXECUTION: "workflow:execution",
            CATEGORY_DIAGNOSTIC: "workflow:diagnostic",
            CATEGORY_MIXED: "workflow:mixed",
        }.get(category, "workflow:mixed")
        return (label,), EVIDENCE_ESTIMATED, "tool-shape"
    return (), EVIDENCE_UNSUPPORTED, "unsupported"


def _overhead_tax_findings(
    rows: list[AgentAttribution],
    options: RuntimeOptions,
) -> list[Finding]:
    summary = agent_summary(rows)
    total = Decimal(str(summary["total_cost_usd_exact"]))
    overhead = Decimal(str(summary["overhead_cost_usd_exact"]))
    share = float(summary["overhead_share"])
    if total <= 0 or overhead < MIN_FINDING_IMPACT_USD or share < OVERHEAD_WARN_SHARE:
        return []
    overhead_rows = [row for row in rows if row.source_category == SOURCE_OVERHEAD]
    return [
        Finding(
            code="OVERHEAD_TAX",
            severity="warn",
            title=f"Background overhead is {share:.0%} of spend",
            detail=(
                "Known background agents crossed the overhead threshold. "
                "Review active automation before another heavy session."
            ),
            action="Inspect overhead agents and disable or tune expensive background automation.",
            payback_action="Reduce background agent spend.",
            scope="agents",
            impact_usd_exact=overhead,
            monthly_projected_savings_usd=_scale_to_monthly(overhead, options),
            confidence="high",
            evidence=(f"{share:.1%} overhead share",),
            evidence_metrics=summary,
            commands=("caliper agents --source-category overhead",),
            event_ids=tuple(row.agent_id for row in overhead_rows),
            evidence_status=_combined_evidence_status(
                [row.evidence_status for row in overhead_rows]
            ),
            sample_size=sum(row.events for row in rows),
            baseline=f"threshold {OVERHEAD_WARN_SHARE:.0%}",
        )
    ]


def _runaway_agent_findings(
    rows: list[AgentAttribution],
    options: RuntimeOptions,
) -> list[Finding]:
    comparable = [row for row in rows if row.cost_usd > 0]
    if len(comparable) < RUNAWAY_MIN_ROWS:
        return []
    costs = [float(row.cost_usd) for row in comparable]
    median = statistics.median(costs)
    scale = _mad(costs, median) * 1.4826
    if scale <= 0 and median > 0:
        scale = median
    if scale <= 0:
        return []
    flagged = [
        row
        for row in comparable
        if float(row.cost_usd) >= median + 3 * scale and float(row.cost_usd) >= median * 3
    ]
    findings: list[Finding] = []
    for row in flagged[:5]:
        excess = row.cost_usd - Decimal(str(median))
        if excess < MIN_FINDING_IMPACT_USD:
            continue
        findings.append(
            Finding(
                code="RUNAWAY_AGENT",
                severity="warn",
                title=f"{row.agent_id} is an agent cost outlier",
                detail=(
                    f"{row.agent_id} spent ${row.cost_usd:,.2f}; comparable median is "
                    f"${median:,.2f}."
                ),
                action=(
                    "Inspect the agent's session, tool-call count, and model before repeating it."
                ),
                payback_action=f"Review {row.agent_id} before re-running.",
                scope="agents",
                impact_usd_exact=excess,
                monthly_projected_savings_usd=_scale_to_monthly(excess, options),
                confidence="medium" if row.evidence_status != EVIDENCE_EXACT else "high",
                evidence=(row.reason, f"{row.events:,} events", f"{row.tool_calls:,} tools"),
                evidence_metrics={
                    "agent_id": row.agent_id,
                    "observed_cost_usd_exact": decimal_string(row.cost_usd),
                    "baseline_median_cost_usd": median,
                    "baseline_scale": scale,
                    "sample_size": len(comparable),
                },
                commands=("caliper agents",),
                event_ids=(row.agent_id,),
                evidence_status=row.evidence_status,
                sample_size=len(comparable),
                baseline=f"median ${median:,.2f}",
            )
        )
    return findings


def _skill_outlier_findings(
    rows: list[SkillAttribution],
    options: RuntimeOptions,
) -> list[Finding]:
    qualified = [row for row in rows if row.invocation_count >= SKILL_MIN_INVOCATIONS]
    if not qualified:
        return []
    total = sum((row.cost_usd for row in rows), Decimal("0"))
    if total <= 0:
        return []
    top = max(qualified, key=lambda row: row.cost_usd)
    share = float(top.cost_usd / total)
    if top.cost_usd < MIN_FINDING_IMPACT_USD or share < 0.50:
        return []
    return [
        Finding(
            code="SKILL_COST_CONCENTRATION",
            severity="info",
            title=f"{top.name} dominates attributed workflow cost",
            detail=(
                f"{top.name} accounts for {share:.0%} of attributed skill/workflow cost. "
                "This is estimated from structural turn boundaries."
            ),
            action="Inspect the workflow before making it a default habit.",
            payback_action=f"Review {top.name} usage.",
            scope="skills",
            impact_usd_exact=top.cost_usd,
            monthly_projected_savings_usd=_scale_to_monthly(top.cost_usd, options),
            confidence="medium",
            evidence=(
                f"{top.invocation_count:,} invocations",
                f"{top.session_count:,} sessions",
                f"{share:.1%} attributed share",
            ),
            evidence_metrics={
                "name": top.name,
                "share": share,
                "invocations": top.invocation_count,
                "attribution_method": top.attribution_method,
            },
            commands=("caliper skills",),
            event_ids=(top.name,),
            evidence_status=top.evidence_status,
            sample_size=top.invocation_count,
            baseline="attributed workflow cost share",
        )
    ]


def _combined_evidence_status(statuses: list[str]) -> str:
    if not statuses:
        return EVIDENCE_UNSUPPORTED
    if all(status == EVIDENCE_EXACT for status in statuses):
        return EVIDENCE_EXACT
    if any(status == EVIDENCE_EXACT for status in statuses):
        return EVIDENCE_PARTIAL
    if any(status == EVIDENCE_ESTIMATED for status in statuses):
        return EVIDENCE_ESTIMATED
    return EVIDENCE_PARTIAL


def _mad(values: list[float], center: float) -> float:
    if not values:
        return 0.0
    return statistics.median(abs(value - center) for value in values)


def _event_key(event: UsageEvent) -> str:
    if event.event_id:
        return event.event_id
    if event.message_id:
        return event.message_id
    if event.dedupe_key:
        return event.dedupe_key
    return f"{event.path}:{event.source_line}:{event.session_id}"


def _scale_to_monthly(impact: Decimal, options: RuntimeOptions) -> Decimal:
    window_days = max((options.end - options.start).total_seconds() / 86_400.0, 1.0)
    return Decimal(str(round(float(impact) * (30.0 / window_days), 4)))


def git_attribution_coverage(events: list[UsageEvent], rate_card: RateCard) -> dict[str, object]:
    """How much spend actually carries a git SHA.

    ``caliper pr`` / ``caliper commit`` can only price the slice of events
    that recorded a commit SHA. Most events don't, so the honest framing is
    a coverage statement: "cost-per-commit covers X% of recorded spend; the
    rest has no SHA." This returns the raw numbers for that disclosure — it
    does **not** infer SHAs (Caliper never fabricates attribution).
    """
    events_total = len(events)
    cost_total = Decimal("0")
    events_with_sha = 0
    cost_with_sha = Decimal("0")
    for event in events:
        cost, _long, _unknown = event_cost(rate_card, event)
        cost_total += cost.cost_usd
        if event.thread.git_sha:
            events_with_sha += 1
            cost_with_sha += cost.cost_usd
    cost_coverage = float(cost_with_sha / cost_total) if cost_total > 0 else 0.0
    sha_coverage = (events_with_sha / events_total) if events_total else 0.0
    return {
        "events_with_sha": events_with_sha,
        "events_total": events_total,
        "sha_coverage": sha_coverage,
        "cost_with_sha_usd_exact": decimal_string(cost_with_sha),
        "cost_total_usd_exact": decimal_string(cost_total),
        "cost_coverage": cost_coverage,
        # Full SHA coverage is the only "exact" story; anything less is partial.
        "evidence_status": "exact" if sha_coverage >= 1.0 and events_total else "partial",
    }


__all__ = [
    "AgentAttribution",
    "SOURCE_DIRECT",
    "SkillAttribution",
    "agent_summary",
    "attribution_findings",
    "build_agent_attributions",
    "build_skill_attributions",
    "git_attribution_coverage",
    "skill_summary",
]
