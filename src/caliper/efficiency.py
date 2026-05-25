"""Inefficiency detection. Quantified dollar findings only.

Each finder is a pure function ``finder(result, options, card) ->
list[Finding]``. Findings carry an exact dollar saving estimate. A
finder that cannot quantify simply does not emit. Deduplication keeps
the single highest-impact finding per event so totals never
double-count.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Callable
from decimal import Decimal

from caliper.aggregation import event_cost
from caliper.arbitrage import ModelAlternative, rank_model_alternatives
from caliper.humanize import session_label_lookup
from caliper.models import (
    Finding,
    LoadResult,
    Recommendation,
    RuntimeOptions,
    Usage,
    UsageEvent,
    decimal_value,
)
from caliper.patterns import (
    is_trivial_turn,
    project_for_event,
    prompt_rot_curve,
    session_event_groups,
    session_first_prompt_hash,
)
from caliper.pricing import (
    LONG_CONTEXT_INPUT_THRESHOLD,
    MODELS_BY_NAME,
    RateCard,
    normalize_model,
)

# Severity levels.
SEV_INFO = "info"
SEV_WARN = "warn"
SEV_FAIL = "fail"

# Finding codes.
CODE_LONG_CONTEXT = "LONG_CONTEXT_MISFIRE"
CODE_REASONING_WASTE = "REASONING_WASTE"
CODE_LOW_CACHE_REUSE = "LOW_CACHE_REUSE"
CODE_MODEL_OVERSELECTION = "MODEL_OVERSELECTION"
CODE_TIER_MISMATCH = "TIER_MISMATCH"
CODE_DUPLICATE_SESSIONS = "DUPLICATE_SESSIONS"
CODE_PROMPT_ROT = "PROMPT_ROT"

ALL_CODES: tuple[str, ...] = (
    CODE_LONG_CONTEXT,
    CODE_REASONING_WASTE,
    CODE_LOW_CACHE_REUSE,
    CODE_MODEL_OVERSELECTION,
    CODE_TIER_MISMATCH,
    CODE_DUPLICATE_SESSIONS,
    CODE_PROMPT_ROT,
)

# Legacy sibling-model map kept for callers that import the constant.
# New recommendations use active rate-card repricing via arbitrage
# alternatives rather than this static cascade.
SIBLING_MODELS: dict[str, str] = {
    "claude-opus-4.7": "claude-sonnet-4.6",
    "claude-sonnet-4.6": "claude-haiku-4.5",
    "claude-haiku-4.5": "gpt-5.4-mini",
    "gpt-5.5": "gpt-5.4",
    "gpt-5.4": "gpt-5.4-mini",
    "gpt-5.3-codex": "gpt-5.4-mini",
    "gpt-5.2": "gpt-5.4-mini",
    "gpt-5.1-codex-max": "gpt-5.4-mini",
}

LOW_CACHE_REUSE_RATIO = 0.20
LOW_CACHE_REUSE_MIN_TOKENS = 20_000
LONG_CONTEXT_PROXIMITY = 0.90  # uncached_input within 10% of threshold
PROMPT_ROT_MULTIPLIER = 2.0
PROMPT_ROT_MIN_EVENTS = 5
TIER_MISMATCH_MAX_EVENTS = 5
DUPLICATE_WINDOW_HOURS = 24
DEFAULT_MIN_IMPACT_USD = Decimal("0.10")
EXTRAPOLATION_DAYS = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event_cost_usd(card: RateCard, event: UsageEvent) -> Decimal:
    cost, _, _ = event_cost(card, event)
    return cost.cost_usd


def _evidence_label(event: UsageEvent) -> str:
    """Short opaque session identifier, safe to emit regardless of
    redaction state (the session id is the rollout filename's GUID)."""
    return event.session_id or event.event_id or event.path.name


def _dedupe_id(event: UsageEvent) -> str:
    if event.event_id:
        return f"event:{event.event_id}"
    if event.message_id:
        return f"message:{event.message_id}"
    if event.dedupe_key:
        return f"dedupe:{event.dedupe_key}"
    return f"event:{event.path}:{event.source_line}:{event.session_id}"


def _scale_to_monthly(impact: Decimal, options: RuntimeOptions) -> Decimal:
    """Project a within-window finding's dollar impact to a 30-day
    monthly view for stakeholders."""
    window_days = max((options.end - options.start).total_seconds() / 86400.0, 1.0)
    if window_days <= 0:
        return impact
    monthly = float(impact) * (EXTRAPOLATION_DAYS / window_days)
    return Decimal(str(round(monthly, 4)))


def _finding_window_scope(scope: str) -> str:
    return scope


def _format_money_exact(value: str) -> str:
    amount = Decimal(value or "0")
    if amount == 0:
        return "$0"
    if abs(amount) < Decimal("0.01"):
        return f"${amount:,.4f}"
    return f"${amount:,.2f}"


# ---------------------------------------------------------------------------
# Finders
# ---------------------------------------------------------------------------


def find_long_context_misfire(
    result: LoadResult,
    options: RuntimeOptions,
    card: RateCard,
) -> list[Finding]:
    """Events triggering the long-context multiplier where the input
    sits within 10% of the threshold — i.e. trimming would dodge it."""
    flagged: list[UsageEvent] = []
    excess_cost = Decimal("0")
    threshold = LONG_CONTEXT_INPUT_THRESHOLD
    near_band_lower = int(threshold * LONG_CONTEXT_PROXIMITY)
    near_band_upper = int(threshold * (2.0 - LONG_CONTEXT_PROXIMITY))
    for event in result.events:
        if event.usage.input_tokens <= threshold:
            continue
        if event.usage.input_tokens > near_band_upper:
            continue
        if event.usage.input_tokens < near_band_lower:
            continue
        model_card = MODELS_BY_NAME.get(normalize_model(event.model))
        if model_card is None or model_card.long_context is None:
            continue
        actual, _, _ = event_cost(card, event)
        trimmed_usage = Usage(
            input_tokens=threshold - 1,
            cached_input_tokens=min(event.usage.cached_input_tokens, threshold - 1),
            output_tokens=event.usage.output_tokens,
            reasoning_output_tokens=event.usage.reasoning_output_tokens,
            total_tokens=event.usage.total_tokens,
        )
        trimmed_cost, _, _ = card.cost_for(trimmed_usage, event.model, event.service_tier)
        delta = actual.cost_usd - trimmed_cost.cost_usd
        if delta <= Decimal("0"):
            continue
        excess_cost += delta
        flagged.append(event)
    if not flagged or excess_cost <= Decimal("0"):
        return []
    return [
        Finding(
            code=CODE_LONG_CONTEXT,
            severity=SEV_WARN,
            title=f"{len(flagged)} events triggered long-context pricing",
            detail=(
                f"{len(flagged)} events crossed the {threshold:,}-token long-context line "
                "by less than 10%; trimming them below the line avoids the long-context "
                "input/output multipliers."
            ),
            action="Pre-trim or summarise context before exceeding the long-context threshold.",
            payback_action=f"Trim {len(flagged)} prompts under {threshold:,} input tokens.",
            scope="home",
            impact_usd_exact=excess_cost,
            monthly_projected_savings_usd=_scale_to_monthly(excess_cost, options),
            confidence="high",
            evidence=tuple(_evidence_label(event) for event in flagged[:3]),
            evidence_metrics={
                "events": len(flagged),
                "threshold": threshold,
            },
            commands=(
                "caliper audit",
                "caliper advise --strict",
            ),
            event_ids=tuple(_dedupe_id(event) for event in flagged),
            evidence_status="estimated",
            sample_size=len(result.events),
            baseline=f"long-context threshold {threshold:,} input tokens",
        )
    ]


def find_reasoning_waste(
    result: LoadResult,
    options: RuntimeOptions,
    card: RateCard,
) -> list[Finding]:
    """Heavy reasoning tokens on turns that did no tool use and produced
    little output — the model overthought a trivial reply."""
    flagged: list[UsageEvent] = []
    total_cost = Decimal("0")
    for event in result.events:
        reasoning = event.usage.reasoning_output_tokens
        if reasoning <= 0:
            continue
        if not is_trivial_turn(event):
            continue
        if event.usage.output_tokens > 0 and reasoning < event.usage.output_tokens * 4:
            continue
        actual, _, _ = event_cost(card, event)
        if actual.cost_usd <= Decimal("0"):
            continue
        # Saving = cost of reasoning portion that would not have been billed.
        without_reasoning = Usage(
            input_tokens=event.usage.input_tokens,
            cached_input_tokens=event.usage.cached_input_tokens,
            output_tokens=event.usage.output_tokens,
            total_tokens=event.usage.total_tokens,
        )
        cheaper, _, _ = card.cost_for(without_reasoning, event.model, event.service_tier)
        delta = actual.cost_usd - cheaper.cost_usd
        if delta <= Decimal("0"):
            continue
        total_cost += delta
        flagged.append(event)
    if not flagged:
        return []
    return [
        Finding(
            code=CODE_REASONING_WASTE,
            severity=SEV_WARN,
            title=f"Reasoning tokens wasted on {len(flagged)} trivial turns",
            detail=(
                f"{len(flagged)} short replies used 4× more reasoning tokens than output. "
                "Lower `reasoning_effort` for these workflows."
            ),
            action="Drop reasoning_effort to low (or off) for low-output assistant turns.",
            payback_action=f"Lower reasoning_effort on {len(flagged)} turns.",
            scope="models",
            impact_usd_exact=total_cost,
            monthly_projected_savings_usd=_scale_to_monthly(total_cost, options),
            confidence="medium",
            evidence=tuple(_evidence_label(event) for event in flagged[:3]),
            evidence_metrics={"events": len(flagged)},
            commands=("caliper audit",),
            event_ids=tuple(_dedupe_id(event) for event in flagged),
            evidence_status="estimated",
            sample_size=len(result.events),
            baseline="no tools, short output, reasoning >= 4x output",
        )
    ]


def find_low_cache_reuse(
    result: LoadResult,
    options: RuntimeOptions,
    card: RateCard,
) -> list[Finding]:
    """Sessions with high uncached input and low cached-input share.
    The dollar lever is the cost difference between paying full input
    rate vs paying the cached read rate on the uncached overflow."""
    findings: list[Finding] = []
    total_saving = Decimal("0")
    poor_sessions: list[str] = []
    sessions_seen = 0
    for session_id, events in session_event_groups(result.events).items():
        input_tokens = sum(e.usage.input_tokens for e in events)
        if input_tokens < LOW_CACHE_REUSE_MIN_TOKENS:
            continue
        cache_reads = sum(e.usage.cache_read_input_tokens for e in events)
        ratio = cache_reads / input_tokens if input_tokens else 0.0
        sessions_seen += 1
        if ratio >= LOW_CACHE_REUSE_RATIO:
            continue
        # Saving = target cache reads × (input_rate - cached-read rate).
        gap_tokens = max(0, int((LOW_CACHE_REUSE_RATIO * input_tokens) - cache_reads))
        if gap_tokens <= 0:
            continue
        model_rates = _rates_for_session(card, events)
        if model_rates is None:
            continue
        input_rate, cached_rate = model_rates
        delta = (decimal_value(gap_tokens) * (input_rate - cached_rate)) / Decimal("1000000")
        if delta <= Decimal("0"):
            continue
        total_saving += delta
        poor_sessions.append(session_id)
    if not poor_sessions or total_saving <= Decimal("0"):
        return findings
    labels = session_label_lookup(result.events, options.timezone)
    findings.append(
        Finding(
            code=CODE_LOW_CACHE_REUSE,
            severity=SEV_INFO,
            title=(
                f"{len(poor_sessions)} sessions are below "
                f"{int(LOW_CACHE_REUSE_RATIO * 100)}% cache reuse"
            ),
            detail=(
                f"{len(poor_sessions)}/{sessions_seen} long sessions reuse less than "
                f"{int(LOW_CACHE_REUSE_RATIO * 100)}% of their input tokens as cache reads. "
                "Pin a stable system prompt and reuse it across turns."
            ),
            action="Adopt cache-friendly stable prefixes (system prompt, files dump).",
            payback_action=f"Stabilise prompts on {len(poor_sessions)} sessions.",
            scope="home",
            impact_usd_exact=total_saving,
            monthly_projected_savings_usd=_scale_to_monthly(total_saving, options),
            confidence="medium",
            evidence=tuple(labels.get(session_id, session_id) for session_id in poor_sessions[:3]),
            evidence_metrics={
                "sessions": len(poor_sessions),
                "session_labels": [
                    labels.get(session_id, session_id) for session_id in poor_sessions[:3]
                ],
                "ratio_threshold": LOW_CACHE_REUSE_RATIO,
            },
            commands=("caliper audit",),
            event_ids=tuple(poor_sessions),
            evidence_status="estimated",
            sample_size=sessions_seen,
            baseline=f"cache-read ratio >= {LOW_CACHE_REUSE_RATIO:.0%}",
        )
    )
    return findings


def _rates_for_session(card: RateCard, events: list[UsageEvent]) -> tuple[Decimal, Decimal] | None:
    """Pick the (input_rate, cached_rate) tuple for the model that
    contributed the most to the session. Returns ``None`` when the
    rate card has no rates for the dominant model."""
    cost_by_model: dict[str, Decimal] = {}
    for event in events:
        cost, _, _ = event_cost(card, event)
        cost_by_model[event.model] = cost_by_model.get(event.model, Decimal("0")) + cost.cost_usd
    if not cost_by_model:
        return None
    dominant_model = max(cost_by_model, key=cost_by_model.get)
    normalized = normalize_model(dominant_model)
    rates_card = card.catalog_cards.get(normalized) or MODELS_BY_NAME.get(normalized)
    if not rates_card or rates_card.api_rates is None:
        return None
    return rates_card.api_rates.input, rates_card.api_rates.cached_input


def find_model_overselection(
    result: LoadResult,
    options: RuntimeOptions,
    card: RateCard,
) -> list[Finding]:
    """Short, tool-free turns whose *current* model has a cheaper priced
    equivalent for the same token shape.

    Flagged turns are grouped by their current model, and each cohort is
    priced against *its own* turns, so the headline model, turn count, and
    savings all describe the same population — a finding can never recommend
    routing a model's turns to something that is pricier for those turns
    (the old code conflated the most-frequent model with savings aggregated
    over a different, mixed pool). The cohort with the largest savings is
    surfaced.
    """
    trivial_by_model: dict[str, list[UsageEvent]] = {}
    for event in result.events:
        if not is_trivial_turn(event):
            continue
        trivial_by_model.setdefault(event.model, []).append(event)
    if not trivial_by_model:
        return []

    best: tuple[Decimal, str, list[UsageEvent], tuple[ModelAlternative, ...]] | None = None
    for model, events in trivial_by_model.items():
        # Alternatives are filtered to cheaper-than-`model` for *these* turns
        # by `_compute_alternatives` (savings = actual − projected, kept only
        # when > 0), so every listed option genuinely saves for this cohort.
        alternatives = rank_model_alternatives(events, card, limit=3)
        if not alternatives:
            continue
        top_saving = Decimal(alternatives[0].estimated_savings_usd_exact)
        if best is None or top_saving > best[0]:
            best = (top_saving, model, events, alternatives)
    if best is None:
        return []

    total_saving, top_model, flagged, alternatives = best
    top_alternative = alternatives[0]
    # The in-family pin (`_alternative_priority`) can rank a same-vendor swap
    # ahead of a cheaper cross-vendor one; name that honestly instead of
    # quoting the top pick while a bigger saver sits on the same line.
    best_by_savings = max(alternatives, key=lambda item: Decimal(item.estimated_savings_usd_exact))
    choices = ", ".join(
        f"{item.model} ({item.vendor}, saves "
        f"{_format_money_exact(item.estimated_savings_usd_exact)})"
        for item in alternatives
    )
    detail = (
        f"{len(flagged):,} short, tool-free turns on {top_model} would price cheaper "
        f"on another model for the same token shape: {choices}."
    )
    if best_by_savings.model != top_alternative.model and (
        Decimal(best_by_savings.estimated_savings_usd_exact) > total_saving
    ):
        detail += (
            f" {top_alternative.model} is the lower-risk pick here; "
            f"{best_by_savings.model} saves the most "
            f"({_format_money_exact(best_by_savings.estimated_savings_usd_exact)})."
        )
    return [
        Finding(
            code=CODE_MODEL_OVERSELECTION,
            severity=SEV_WARN,
            title=f"{len(flagged):,} short, tool-free {top_model} turns could run cheaper",
            detail=detail,
            action=(
                f"Route these {top_model} turns to {top_alternative.model} or another "
                "ranked cheaper alternative."
            ),
            payback_action=f"Route short {top_model} turns to {top_alternative.model}.",
            scope="models",
            impact_usd_exact=total_saving,
            monthly_projected_savings_usd=_scale_to_monthly(total_saving, options),
            confidence="medium",
            evidence=tuple(_evidence_label(event) for event in flagged[:3]),
            evidence_metrics={
                "events": len(flagged),
                "top_model": top_model,
                "sibling": top_alternative.model,
                "top_alternative": top_alternative.to_record(),
                "alternatives": [item.to_record() for item in alternatives],
            },
            commands=(
                "caliper audit",
                f"caliper whatif --hypothetical-model {top_alternative.model}",
            ),
            event_ids=tuple(_dedupe_id(event) for event in flagged),
            evidence_status="estimated",
            sample_size=len(result.events),
            baseline="trivial-turn heuristic with active rate-card alternatives",
        )
    ]


def find_tier_mismatch(
    result: LoadResult,
    options: RuntimeOptions,
    card: RateCard,
) -> list[Finding]:
    """Priority-tier on sessions with very few events — the user is
    paying for throughput they did not need."""
    per_session = session_event_groups(result.events)
    flagged_sessions: list[str] = []
    total_saving = Decimal("0")
    for session_id, events in per_session.items():
        if len(events) > TIER_MISMATCH_MAX_EVENTS:
            continue
        if not any(event.service_tier == "fast" for event in events):
            continue
        for event in events:
            actual, _, _ = event_cost(card, event)
            standard, _, _ = card.cost_for(event.usage, event.model, "standard")
            delta = actual.cost_usd - standard.cost_usd
            if delta > Decimal("0"):
                total_saving += delta
        flagged_sessions.append(session_id)
    if not flagged_sessions or total_saving <= Decimal("0"):
        return []
    labels = session_label_lookup(result.events, options.timezone)
    return [
        Finding(
            code=CODE_TIER_MISMATCH,
            severity=SEV_INFO,
            title=f"{len(flagged_sessions)} short sessions paid for priority tier",
            detail=(
                f"{len(flagged_sessions)} sessions with ≤{TIER_MISMATCH_MAX_EVENTS} events "
                "ran on priority tier. Standard tier is cheaper for one-off lookups."
            ),
            action="Reserve priority tier for long, throughput-bound runs.",
            payback_action="Move throwaway sessions to standard tier.",
            scope="home",
            impact_usd_exact=total_saving,
            monthly_projected_savings_usd=_scale_to_monthly(total_saving, options),
            confidence="medium",
            evidence=tuple(
                labels.get(session_id, session_id) for session_id in flagged_sessions[:3]
            ),
            evidence_metrics={
                "sessions": len(flagged_sessions),
                "session_labels": [
                    labels.get(session_id, session_id) for session_id in flagged_sessions[:3]
                ],
            },
            commands=("caliper audit", "caliper --service-tier standard"),
            event_ids=tuple(flagged_sessions),
            evidence_status="estimated",
            sample_size=len(per_session),
            baseline=f"short sessions <= {TIER_MISMATCH_MAX_EVENTS} events",
        )
    ]


def find_duplicate_sessions(
    result: LoadResult,
    options: RuntimeOptions,
    card: RateCard,
) -> list[Finding]:
    """Sessions with the same project + first-prompt-hash within 24h.
    Keep the cheapest, treat the rest as waste."""
    groups: dict[tuple[str, str], list[tuple[UsageEvent, Decimal]]] = {}
    for event in result.events:
        prompt_hash = session_first_prompt_hash(event)
        if not prompt_hash:
            continue
        key = (project_for_event(event), prompt_hash)
        cost = _event_cost_usd(card, event)
        groups.setdefault(key, []).append((event, cost))

    # Bucket by session, then group same (project, hash) within 24h.
    duplicate_total = Decimal("0")
    duplicate_session_ids: list[str] = []
    compared_sessions: set[str] = set()
    for items in groups.values():
        per_session: dict[str, tuple[dt.datetime, Decimal]] = {}
        for event, cost in items:
            session_id = event.session_id
            if not session_id:
                continue
            ts_existing, cost_existing = per_session.get(
                session_id, (event.timestamp, Decimal("0"))
            )
            per_session[session_id] = (max(ts_existing, event.timestamp), cost_existing + cost)
            compared_sessions.add(session_id)
        if len(per_session) < 2:
            continue
        sorted_sessions = sorted(per_session.items(), key=lambda kv: kv[1][0])
        clusters: list[list[tuple[str, dt.datetime, Decimal]]] = []
        current: list[tuple[str, dt.datetime, Decimal]] = []
        for session_id, (ts, cost) in sorted_sessions:
            if current and (ts - current[-1][1]) > dt.timedelta(hours=DUPLICATE_WINDOW_HOURS):
                clusters.append(current)
                current = []
            current.append((session_id, ts, cost))
        if current:
            clusters.append(current)
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            costs = sorted(cluster, key=lambda row: row[2])
            keep = costs[0]
            for session_id, _ts, cost in costs[1:]:
                duplicate_total += cost
                duplicate_session_ids.append(session_id)
            _ = keep
    if not duplicate_session_ids or duplicate_total <= Decimal("0"):
        return []
    labels = session_label_lookup(result.events, options.timezone)
    return [
        Finding(
            code=CODE_DUPLICATE_SESSIONS,
            severity=SEV_WARN,
            title=f"{len(duplicate_session_ids)} duplicate sessions found within 24h",
            detail=(
                f"{len(duplicate_session_ids)} sessions started with the same prompt and "
                "project as a session within the previous 24 hours. Keep the cheapest "
                "and skip the rest."
            ),
            action="De-duplicate by reusing prior session output rather than re-running.",
            payback_action=f"Skip {len(duplicate_session_ids)} re-runs.",
            scope="sessions",
            impact_usd_exact=duplicate_total,
            monthly_projected_savings_usd=_scale_to_monthly(duplicate_total, options),
            confidence="medium",
            evidence=tuple(
                labels.get(session_id, session_id) for session_id in duplicate_session_ids[:3]
            ),
            evidence_metrics={
                "sessions": len(duplicate_session_ids),
                "session_labels": [
                    labels.get(session_id, session_id) for session_id in duplicate_session_ids[:3]
                ],
            },
            commands=("caliper audit",),
            event_ids=tuple(duplicate_session_ids),
            evidence_status="estimated",
            sample_size=len(compared_sessions),
            baseline=f"same project and first-prompt hash within {DUPLICATE_WINDOW_HOURS}h",
        )
    ]


def find_prompt_rot(
    result: LoadResult,
    options: RuntimeOptions,
    card: RateCard,
) -> list[Finding]:
    """Sessions whose uncached_input doubles across the run while output
    stays flat — context is bloating without commensurate value."""
    flagged_sessions: list[str] = []
    total_saving = Decimal("0")
    per_session = session_event_groups(result.events)
    for session_id, events in per_session.items():
        if len(events) < PROMPT_ROT_MIN_EVENTS:
            continue
        curve = prompt_rot_curve(events)
        if not curve or curve[0] <= 0:
            continue
        peak = max(curve)
        if peak < curve[0] * PROMPT_ROT_MULTIPLIER:
            continue
        outputs = [e.usage.output_tokens for e in events]
        if not outputs:
            continue
        first_output = outputs[0] or 1
        last_output = outputs[-1] or 1
        if last_output > first_output * 1.5:
            continue
        # Excess uncached input = total_uncached - first_uncached × len.
        baseline_total = curve[0] * len(curve)
        actual_total = sum(curve)
        excess = max(0, actual_total - baseline_total)
        if excess <= 0:
            continue
        rates = _rates_for_session(card, events)
        if rates is None:
            continue
        input_rate, _ = rates
        delta = (decimal_value(excess) * input_rate) / Decimal("1000000")
        if delta <= Decimal("0"):
            continue
        total_saving += delta
        flagged_sessions.append(session_id)
    if not flagged_sessions or total_saving <= Decimal("0"):
        return []
    labels = session_label_lookup(result.events, options.timezone)
    return [
        Finding(
            code=CODE_PROMPT_ROT,
            severity=SEV_WARN,
            title=f"{len(flagged_sessions)} sessions show prompt rot",
            detail=(
                f"{len(flagged_sessions)} sessions doubled their uncached input across the run "
                "without producing more output. Compact context between turns."
            ),
            action="Compact or summarise prior turns instead of replaying the full history.",
            payback_action=f"Compact context on {len(flagged_sessions)} sessions.",
            scope="sessions",
            impact_usd_exact=total_saving,
            monthly_projected_savings_usd=_scale_to_monthly(total_saving, options),
            confidence="medium",
            evidence=tuple(
                labels.get(session_id, session_id) for session_id in flagged_sessions[:3]
            ),
            evidence_metrics={
                "sessions": len(flagged_sessions),
                "session_labels": [
                    labels.get(session_id, session_id) for session_id in flagged_sessions[:3]
                ],
            },
            commands=("caliper audit",),
            event_ids=tuple(flagged_sessions),
            evidence_status="estimated",
            sample_size=len(per_session),
            baseline=f"uncached input growth >= {PROMPT_ROT_MULTIPLIER:.1f}x",
        )
    ]


# ---------------------------------------------------------------------------
# Registry + audit + recommend
# ---------------------------------------------------------------------------


FinderFn = Callable[[LoadResult, RuntimeOptions, RateCard], list[Finding]]

FINDER_REGISTRY: dict[str, FinderFn] = {
    CODE_LONG_CONTEXT: find_long_context_misfire,
    CODE_REASONING_WASTE: find_reasoning_waste,
    CODE_LOW_CACHE_REUSE: find_low_cache_reuse,
    CODE_MODEL_OVERSELECTION: find_model_overselection,
    CODE_TIER_MISMATCH: find_tier_mismatch,
    CODE_DUPLICATE_SESSIONS: find_duplicate_sessions,
    CODE_PROMPT_ROT: find_prompt_rot,
}


def run_audit(
    result: LoadResult,
    options: RuntimeOptions,
    card: RateCard,
    *,
    codes: list[str] | None = None,
    min_impact_usd: Decimal | None = None,
) -> list[Finding]:
    """Run every selected finder and return findings sorted by impact desc.

    Findings under ``min_impact_usd`` (default $0.10) are dropped to keep
    the surface noise-free. Pass ``min_impact_usd=Decimal("0")`` to keep
    everything.
    """
    threshold = DEFAULT_MIN_IMPACT_USD if min_impact_usd is None else min_impact_usd
    selected_codes = codes or list(ALL_CODES)
    out: list[Finding] = []
    for code in selected_codes:
        finder = FINDER_REGISTRY.get(code)
        if finder is None:
            continue
        for finding in finder(result, options, card):
            if finding.impact_usd_exact >= threshold:
                out.append(finding)
    return _dedupe_findings(out)


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    """Suppress lower-ranked findings that reuse a finder-provided id.

    Finder ids may be event- or session-scoped. To avoid pretending a
    proportional split is exact, any overlap drops the lower-ranked
    finding rather than scaling its dollar impact.
    """
    if not findings:
        return []

    severity_rank = {SEV_FAIL: 0, SEV_WARN: 1, SEV_INFO: 2}
    confidence_rank = {"high": 0, "medium": 1, "low": 2}

    # Sort so the "winning" findings appear first (best impact, then severity, then confidence).
    ranked = sorted(
        findings,
        key=lambda f: (
            -float(f.impact_usd_exact),
            severity_rank.get(f.severity, 9),
            confidence_rank.get(f.confidence, 9),
            f.code,
        ),
    )
    seen: set[str] = set()
    kept: list[Finding] = []
    for finding in ranked:
        overlap = set(finding.event_ids) & seen
        if not finding.event_ids:
            kept.append(finding)
            continue
        if overlap:
            continue
        seen.update(finding.event_ids)
        kept.append(finding)
    return sorted(kept, key=lambda f: -float(f.impact_usd_exact))


def total_savings_usd(findings: list[Finding]) -> Decimal:
    return sum((f.impact_usd_exact for f in findings), Decimal("0"))


def monthly_projected_savings_usd(findings: list[Finding]) -> Decimal:
    return sum((f.monthly_projected_savings_usd for f in findings), Decimal("0"))


def rank_recommendations(
    findings: list[Finding],
    *,
    top: int = 5,
) -> list[Recommendation]:
    """Rank findings into action-first :class:`Recommendation` records
    for the dashboard's advisor slot and the ``caliper recommend``
    command."""
    confidence_weight = {"high": 1.0, "medium": 0.75, "low": 0.5}
    ranked = sorted(
        findings,
        key=lambda f: -float(f.impact_usd_exact) * confidence_weight.get(f.confidence, 0.5),
    )[:top]
    return [
        Recommendation(
            rank=index + 1,
            title=finding.title,
            payback_action=finding.payback_action,
            detail=finding.detail,
            impact_usd_exact=finding.impact_usd_exact,
            monthly_projected_savings_usd=finding.monthly_projected_savings_usd,
            confidence=finding.confidence,
            source_code=finding.code,
            commands=finding.commands,
        )
        for index, finding in enumerate(ranked)
    ]


def confidence_score(findings: list[Finding]) -> float:
    """Aggregate confidence weighted by dollar impact. 1.0 = all-high."""
    if not findings:
        return 0.0
    weights = {"high": 1.0, "medium": 0.66, "low": 0.33}
    weighted = 0.0
    total = 0.0
    for finding in findings:
        impact = float(finding.impact_usd_exact)
        weighted += weights.get(finding.confidence, 0.5) * impact
        total += impact
    return weighted / total if total else 0.0


def waste_share_of_spend(findings: list[Finding], total_spend_usd: Decimal) -> float:
    """Quantified waste as a fraction of total spend. Used by `doctor`
    and the dashboard banner to escalate when waste > 5% of bill."""
    total_waste = float(total_savings_usd(findings))
    spend = float(total_spend_usd)
    if spend <= 0:
        return 0.0
    return total_waste / spend


def median_finding_impact(findings: list[Finding]) -> Decimal:
    if not findings:
        return Decimal("0")
    values = [float(f.impact_usd_exact) for f in findings]
    return Decimal(str(statistics.median(values)))


__all__ = [
    "ALL_CODES",
    "CODE_DUPLICATE_SESSIONS",
    "CODE_LONG_CONTEXT",
    "CODE_LOW_CACHE_REUSE",
    "CODE_MODEL_OVERSELECTION",
    "CODE_PROMPT_ROT",
    "CODE_REASONING_WASTE",
    "CODE_TIER_MISMATCH",
    "DEFAULT_MIN_IMPACT_USD",
    "FINDER_REGISTRY",
    "SEV_FAIL",
    "SEV_INFO",
    "SEV_WARN",
    "SIBLING_MODELS",
    "confidence_score",
    "find_duplicate_sessions",
    "find_long_context_misfire",
    "find_low_cache_reuse",
    "find_model_overselection",
    "find_prompt_rot",
    "find_reasoning_waste",
    "find_tier_mismatch",
    "median_finding_impact",
    "monthly_projected_savings_usd",
    "rank_recommendations",
    "run_audit",
    "total_savings_usd",
    "waste_share_of_spend",
]
