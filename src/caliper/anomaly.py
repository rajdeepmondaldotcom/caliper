"""Statistical anomaly detection over usage events.

Pure stdlib. Returns :class:`Anomaly` records carrying both the σ
distance from baseline and the dollar impact of the deviation so the
dashboard can present a single, ranked "what stands out" list.
"""

from __future__ import annotations

import bisect
import datetime as dt
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from caliper.aggregation import event_cost
from caliper.models import UNKNOWN_PROJECT, Aggregate, Anomaly, UsageEvent
from caliper.pricing import RateCard
from caliper.timeutil import load_timezone

SESSION_SIGMA_DEFAULT = 3.0
DAILY_SIGMA_DEFAULT = 2.5
MIN_SAMPLES_FOR_DETECTION = 4

# Tightened gating so anomalies are *useful*. The combination of these
# three constants prevents the "tiny-baseline → astronomical σ" pathology
# that surfaces when sparse cost data lets the median collapse to zero.
#
# * ``ACTIVE_DAY_THRESHOLD`` — below this dollar value, a day/session
#   doesn't count toward the baseline at all. Inactive days drowning out
#   the median was the actual source of the 354,210σ bug.
# * ``FOLD_CHANGE_MIN`` — require observed ≥ 3× the active-day median.
#   Standard heuristic for cloud-cost anomaly detection (AWS / GCP both
#   surface fold-change in their UX); doubles as a sanity check on σ.
# * ``MIN_IMPACT_USD`` — a $0.40 spike against a $0.10 baseline is 4×
#   but isn't worth interrupting the user. Hard floor of $1 absolute
#   keeps the section signal-rich.
# * ``SIGMA_DISPLAY_CAP`` — anything past this is a math artifact, not
#   a real distance. Surface it as "extreme" rather than a wild number.
ACTIVE_DAY_THRESHOLD = 0.01
FOLD_CHANGE_MIN = 3.0
MIN_IMPACT_USD = 1.0
SIGMA_DISPLAY_CAP = 20.0

# Efficiency-regression detector. The raw-cost detectors above answer "what
# cost a lot" — which mostly means "a busy day", something the user already
# knows. This one answers the more useful question: "where did I pay MORE PER
# UNIT OF WORK than usual?" It scores each substantial session on its cost per
# 1M tokens against prior sessions of similar size in the same project+model
# cohort, so a normal-volume-but-inefficient session (cache loss, model drift,
# tool thrash) surfaces even when its absolute cost is unremarkable. Stats are
# rate-appropriate (not the dollar-calibrated baseline above): robust z on the
# rate with a relative scale floor, gated by token exposure and dollar impact.
EFFICIENCY_SIGMA = 3.0
MIN_EFFICIENCY_TOKENS = 200_000
MIN_EFFICIENCY_COHORT = 4
EFFICIENCY_SCALE_FLOOR_FRAC = 0.10


@dataclass(frozen=True)
class _Observation:
    kind: str
    timestamp: dt.datetime
    order: tuple[int, str]
    label: str
    observed: float
    cohort_key: str
    cohort_label: str
    comparison_scope: str
    dedupe_key: str


def _median_of_sorted(values: list[float]) -> float:
    """``statistics.median`` for an already-sorted, non-empty list, in O(1).

    Byte-identical to :func:`statistics.median`: the median of a multiset is
    its middle order statistic(s), independent of how the input was ordered.
    """
    n = len(values)
    mid = n // 2
    if n % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def _merge_sorted(left: list[float], right: list[float]) -> list[float]:
    """Merge two ascending lists into one ascending list (stable, O(n+m))."""
    out: list[float] = []
    i = j = 0
    n, m = len(left), len(right)
    while i < n and j < m:
        if left[i] <= right[j]:
            out.append(left[i])
            i += 1
        else:
            out.append(right[j])
            j += 1
    if i < n:
        out.extend(left[i:])
    if j < m:
        out.extend(right[j:])
    return out


def _mad_of_sorted(sorted_base: list[float], center: float) -> float:
    """MAD over an already-sorted base, without re-sorting the deviations.

    The absolute deviations ``|v - center|`` are V-shaped around ``center``:
    descending for ``v < center`` then ascending for ``v >= center``. Each
    side is monotone, so reversing the left side and merging yields the same
    sorted deviation multiset that ``sorted(abs(v - center) ...)`` would —
    and IEEE subtraction guarantees ``center - v == abs(v - center)`` exactly
    — so the median is byte-identical to the previous implementation while
    dropping the per-step ``O(n log n)`` sort to ``O(n)``.
    """
    if not sorted_base:
        return 0.0
    split = bisect.bisect_left(sorted_base, center)
    left_dev = [center - v for v in reversed(sorted_base[:split])]
    right_dev = [v - center for v in sorted_base[split:]]
    return _median_of_sorted(_merge_sorted(left_dev, right_dev))


def _baseline_stats_from_sorted(sorted_all: list[float]) -> tuple[float, float]:
    """``_baseline_stats`` for an already-sorted value series.

    This is the hot path: :func:`_score_observations` maintains the prior
    window pre-sorted (via ``bisect.insort``) so the per-row baseline costs
    ``O(n)`` instead of the old three full sorts. Because the active subset
    (``v >= ACTIVE_DAY_THRESHOLD``) is a contiguous suffix of the sorted
    window, it's found with one ``bisect``. Output is identical to
    :func:`_baseline_stats` — proven byte-for-byte in
    ``tests/test_anomaly_equivalence.py``.
    """
    n = len(sorted_all)
    if n < MIN_SAMPLES_FOR_DETECTION:
        return 0.0, 0.0
    active_start = bisect.bisect_left(sorted_all, ACTIVE_DAY_THRESHOLD)
    active_count = n - active_start
    base = sorted_all[active_start:] if active_count >= MIN_SAMPLES_FOR_DETECTION else sorted_all
    median = _median_of_sorted(base)
    mad_scale = _mad_of_sorted(base, median) * 1.4826
    iqr_scale = 0.0
    if len(base) >= 4:
        # ``method="exclusive"`` matches the classic Tukey quartile definition;
        # quantiles re-sorts internally, which is O(n) on already-sorted input.
        q1, _q2, q3 = statistics.quantiles(base, n=4, method="exclusive")
        iqr_scale = max(0.0, (q3 - q1) / 1.349)
    return median, max(mad_scale, iqr_scale, median * 0.10, 1.0)


def _baseline_stats(values: list[float]) -> tuple[float, float]:
    """Return ``(median, robust_scale)`` for the value series.

    The scale is built so it never collapses on sparse / zero-inflated
    data — that's the bug class that produced 354,210σ readings in
    the old implementation. Three layers of defence:

    1. **Active-subset preference.** When ≥ ``MIN_SAMPLES_FOR_DETECTION``
       values are above :data:`ACTIVE_DAY_THRESHOLD`, the baseline is
       built from the active subset, so a run of zero-cost days can't
       pull the median to zero. When there aren't enough active
       values, we fall back to the full distribution (otherwise a
       single big session against a sea of pennies would skip
       detection entirely).
    2. **Three-way robust scale.** We take ``max(MAD × 1.4826,
       IQR / 1.349, median × 0.10)``. MAD handles outlier-heavy
       distributions; IQR (Tukey's robust σ) handles skew; the
       ``median × 10%`` floor guarantees a 10× spike registers as
       ≥ 10σ even when every active value is identical.
    3. **Absolute floor of $1.** No matter what, scale ≥ $1.00. This
       is the contract that makes the σ output bounded for sparse data
       — a $300 spike against a $0 median lands at 300σ, capped to 20
       for display, instead of the runaway 354,210σ from before.

    Returns ``(0.0, 0.0)`` only when there are too few samples to
    compute statistics at all.

    Thin wrapper over :func:`_baseline_stats_from_sorted` (one sort here for
    callers passing an unsorted series; the hot path keeps the window sorted
    and calls the sorted core directly). Output is unchanged.
    """
    return _baseline_stats_from_sorted(sorted(values))


def _z(value: float, mean: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    return (value - mean) / scale


def _qualifies(
    observed: float, center: float, scale: float, sigma_threshold: float
) -> tuple[bool, float]:
    """Apply all three anomaly gates and return ``(is_anomaly, clamped_z)``.

    Centralising the gate logic means the four detectors stay in
    lockstep — adjusting the fold-change here flips them all together.
    """
    if scale <= 0:
        return False, 0.0
    z = _z(observed, center, scale)
    impact = observed - center
    fold = observed / max(center, ACTIVE_DAY_THRESHOLD)
    if z < sigma_threshold:
        return False, z
    if impact < MIN_IMPACT_USD:
        return False, z
    if fold < FOLD_CHANGE_MIN:
        return False, z
    return True, min(z, SIGMA_DISPLAY_CAP)


def human_label(observed: float, baseline_center: float, z_score: float) -> str:
    """A plain-English gloss for an anomaly's magnitude.

    ``σ=20.0`` means nothing to a non-engineer; "≈20× your typical spend"
    does. Derived only from fields already on the anomaly (no new stats), so
    CLI and dashboard stay in lockstep. JSON keeps the raw ``z_score`` /
    ``impact_usd_exact`` for scripting; this is a display aid only.
    """
    # At the display cap the fold-change is a math artifact (near-zero
    # baseline), so a precise "≈3887×" reads as noise — say "extreme" instead.
    if z_score >= SIGMA_DISPLAY_CAP:
        return "extreme — far above your typical spend for this cohort"
    if baseline_center < ACTIVE_DAY_THRESHOLD:
        return "far above near-zero typical spend for this cohort"
    fold = observed / baseline_center
    if fold >= 100:
        return "far above your typical spend for this cohort"
    return f"≈{fold:.0f}× your typical spend for this cohort"


def _sort_key(item: Anomaly) -> tuple[Decimal, float, str, str]:
    return (-item.impact_usd_exact, -item.z_score, item.kind, item.label)


def _most_common(counter: Counter[str], fallback: str) -> str:
    if not counter:
        return fallback
    value, _count = counter.most_common(1)[0]
    return value or fallback


def _impact_percent(observed: float, center: float) -> float | None:
    if center < ACTIVE_DAY_THRESHOLD:
        return None
    return round(((observed - center) / center) * 100.0, 1)


def _scope_reason(
    observed: float,
    center: float,
    sample_count: int,
    impact_percent: float | None,
) -> str:
    if impact_percent is None:
        return f"above near-zero typical spend across {sample_count} comparable observations"
    pct = f"{impact_percent:.0f}" if impact_percent.is_integer() else f"{impact_percent:.1f}"
    return f"{pct}% above expected across {sample_count} comparable observations"


def _score_observations(
    observations: list[_Observation],
    *,
    sigma_threshold: float,
) -> list[Anomaly]:
    by_cohort: dict[str, list[_Observation]] = {}
    for item in observations:
        by_cohort.setdefault(item.cohort_key, []).append(item)

    anomalies: list[Anomaly] = []
    for rows in by_cohort.values():
        # Keep the expanding prior window pre-sorted so each row's baseline is
        # O(n) (one bisect + linear stats) instead of three full sorts. Output
        # is identical to scoring against the unsorted window — see
        # tests/test_anomaly_equivalence.py.
        sorted_prior: list[float] = []
        for row in sorted(rows, key=lambda r: (r.order, r.timestamp, r.label)):
            center, scale = _baseline_stats_from_sorted(sorted_prior)
            if scale > 0:
                ok, z = _qualifies(row.observed, center, scale, sigma_threshold)
                if ok:
                    sample_count = len(sorted_prior)
                    impact = Decimal(str(max(0.0, row.observed - center)))
                    impact_percent = _impact_percent(row.observed, center)
                    anomalies.append(
                        Anomaly(
                            kind=row.kind,
                            timestamp=row.timestamp,
                            label=row.label,
                            observed=row.observed,
                            baseline_center=center,
                            baseline_scale=scale,
                            z_score=z,
                            impact_usd_exact=impact,
                            comparison_scope=row.comparison_scope,
                            baseline_sample_count=sample_count,
                            cohort_key=row.cohort_key,
                            cohort_label=row.cohort_label,
                            reason=_scope_reason(
                                row.observed,
                                center,
                                sample_count,
                                impact_percent,
                            ),
                            dedupe_key=row.dedupe_key,
                            impact_percent=impact_percent,
                        )
                    )
            bisect.insort(sorted_prior, row.observed)
    return sorted(anomalies, key=_sort_key)


def _session_observations(events: Iterable[UsageEvent], rate_card: RateCard) -> list[_Observation]:
    sessions: dict[str, dict[str, object]] = {}
    for event in events:
        if not event.session_id:
            continue
        cost, _, _ = event_cost(rate_card, event)
        item = sessions.setdefault(
            event.session_id,
            {
                "first_seen": event.timestamp,
                "last_seen": event.timestamp,
                "cost": 0.0,
                "projects": Counter(),
                "models": Counter(),
                "tiers": Counter(),
                "vendors": Counter(),
            },
        )
        item["first_seen"] = min(item["first_seen"], event.timestamp)  # type: ignore[arg-type]
        item["last_seen"] = max(item["last_seen"], event.timestamp)  # type: ignore[arg-type]
        item["cost"] = float(item["cost"]) + float(cost.cost_usd)
        item["projects"][event.thread.cwd or UNKNOWN_PROJECT] += 1  # type: ignore[index]
        item["models"][event.model or "unknown-model"] += 1  # type: ignore[index]
        item["tiers"][event.service_tier or "unknown-tier"] += 1  # type: ignore[index]
        item["vendors"][event.vendor or "unknown-vendor"] += 1  # type: ignore[index]

    out: list[_Observation] = []
    for session_id, item in sessions.items():
        project = _most_common(item["projects"], UNKNOWN_PROJECT)  # type: ignore[arg-type]
        model = _most_common(item["models"], "unknown-model")  # type: ignore[arg-type]
        tier = _most_common(item["tiers"], "unknown-tier")  # type: ignore[arg-type]
        vendor = _most_common(item["vendors"], "unknown-vendor")  # type: ignore[arg-type]
        last_seen = item["last_seen"]
        assert isinstance(last_seen, dt.datetime)
        cohort_key = "\0".join(("session", project, model, tier, vendor))
        out.append(
            _Observation(
                kind="session_spike",
                timestamp=last_seen,
                order=(int(last_seen.timestamp()), session_id),
                label=session_id,
                observed=float(item["cost"]),
                cohort_key=cohort_key,
                cohort_label=f"{project} / {model} / {tier}",
                comparison_scope="prior sessions in same project/model/tier cohort",
                dedupe_key=f"session:{session_id}",
            )
        )
    return out


def _daily_observations(daily: list[Aggregate]) -> list[_Observation]:
    out: list[_Observation] = []
    for row in daily:
        timestamp = row.last_seen or row.first_seen or dt.datetime.now(tz=dt.UTC)
        out.append(
            _Observation(
                kind="daily_spike",
                timestamp=timestamp,
                order=(int(timestamp.timestamp()), row.label),
                label=row.label,
                observed=float(row.costs.cost_usd),
                cohort_key="daily\0selected-window",
                cohort_label="selected window",
                comparison_scope="prior days in selected window",
                dedupe_key=f"daily:{row.label}",
            )
        )
    return out


def _model_day_observations(
    events: Iterable[UsageEvent],
    rate_card: RateCard,
    timezone: str = "UTC",
) -> list[_Observation]:
    tz = load_timezone(timezone)
    per_model_day: dict[tuple[str, str, str, dt.date], tuple[dt.datetime, float]] = {}
    for event in events:
        if not event.model:
            continue
        cost, _, _ = event_cost(rate_card, event)
        day = event.timestamp.astimezone(tz).date()
        model = event.model
        tier = event.service_tier or "unknown-tier"
        vendor = event.vendor or "unknown-vendor"
        key = (model, tier, vendor, day)
        seen, total = per_model_day.get(key, (event.timestamp, 0.0))
        per_model_day[key] = (max(seen, event.timestamp), total + float(cost.cost_usd))

    out: list[_Observation] = []
    for (model, tier, vendor, day), (timestamp, cost) in per_model_day.items():
        cohort_key = "\0".join(("model-day", model, tier, vendor))
        day_label = day.isoformat()
        out.append(
            _Observation(
                kind="model_day_spike",
                timestamp=timestamp,
                order=(int(timestamp.timestamp()), day_label),
                label=f"{model} / {day_label}",
                observed=cost,
                cohort_key=cohort_key,
                cohort_label=f"{model} / {tier}",
                comparison_scope="prior active days for same model/tier cohort",
                dedupe_key=f"model-day:{model}:{tier}:{vendor}:{day_label}",
            )
        )
    return out


def _project_day_observations(
    events: Iterable[UsageEvent],
    rate_card: RateCard,
    timezone: str,
) -> list[_Observation]:
    tz = load_timezone(timezone)
    per_project_day: dict[tuple[str, dt.date], tuple[dt.datetime, float]] = {}
    for event in events:
        project = event.thread.cwd or UNKNOWN_PROJECT
        day = event.timestamp.astimezone(tz).date()
        key = (project, day)
        seen, total = per_project_day.get(key, (event.timestamp, 0.0))
        cost, _, _ = event_cost(rate_card, event)
        per_project_day[key] = (max(seen, event.timestamp), total + float(cost.cost_usd))

    out: list[_Observation] = []
    for (project, day), (timestamp, cost) in per_project_day.items():
        day_label = day.isoformat()
        out.append(
            _Observation(
                kind="project_day_spike",
                timestamp=timestamp,
                order=(int(timestamp.timestamp()), day_label),
                label=f"{project} / {day_label}",
                observed=cost,
                cohort_key=f"project-day\0{project}",
                cohort_label=project,
                comparison_scope="prior active days in same project",
                dedupe_key=f"project-day:{project}:{day_label}",
            )
        )
    return out


def _specificity_rank(item: Anomaly) -> int:
    return {
        "session_spike": 0,
        "project_day_spike": 1,
        "model_day_spike": 2,
        "daily_spike": 3,
    }.get(item.kind, 9)


def _incident_key(item: Anomaly) -> str:
    day = item.timestamp.date().isoformat()
    observed_cents = int(round(item.observed * 100))
    impact_cents = int(round(float(item.impact_usd_exact) * 100))
    return f"{day}:{observed_cents}:{impact_cents}"


def _prefer_incident_item(item: Anomaly) -> tuple[int, Decimal, float, str, str]:
    return (_specificity_rank(item), *_sort_key(item))


def _dedupe_anomalies(items: Iterable[Anomaly]) -> list[Anomaly]:
    by_key: dict[str, Anomaly] = {}
    for item in items:
        key = item.dedupe_key or f"{item.kind}:{item.label}"
        existing = by_key.get(key)
        if existing is None or _sort_key(item) < _sort_key(existing):
            by_key[key] = item

    by_incident: dict[str, Anomaly] = {}
    for item in by_key.values():
        key = _incident_key(item)
        existing = by_incident.get(key)
        if existing is None or _prefer_incident_item(item) < _prefer_incident_item(existing):
            by_incident[key] = item
    return sorted(by_incident.values(), key=_sort_key)


def detect_actionable_anomalies(
    events: Iterable[UsageEvent],
    rate_card: RateCard,
    timezone: str,
    *,
    daily: list[Aggregate] | None = None,
) -> list[Anomaly]:
    """Return deduped anomalies that have comparable prior history."""
    event_list = list(events)
    raw = (
        detect_session_anomalies(event_list, rate_card)
        + ([] if daily is None else detect_daily_anomalies(daily))
        + detect_model_anomalies(event_list, rate_card, timezone=timezone)
        + detect_project_daily_anomalies(event_list, rate_card, timezone)
        + detect_efficiency_regressions(event_list, rate_card)
    )
    return _dedupe_anomalies(raw)


def detect_session_anomalies(
    events: Iterable[UsageEvent],
    rate_card: RateCard,
    *,
    sigma_threshold: float = SESSION_SIGMA_DEFAULT,
) -> list[Anomaly]:
    """Flag sessions whose cost is ``>= sigma_threshold`` above baseline.

    Returns an empty list when fewer than
    :data:`MIN_SAMPLES_FOR_DETECTION` sessions are present — z-scores
    over tiny samples are noise, not signal.
    """
    return _score_observations(
        _session_observations(events, rate_card),
        sigma_threshold=sigma_threshold,
    )


def detect_daily_anomalies(
    daily: list[Aggregate],
    *,
    sigma_threshold: float = DAILY_SIGMA_DEFAULT,
) -> list[Anomaly]:
    """Flag day-level cost spikes."""
    return _score_observations(
        _daily_observations(daily),
        sigma_threshold=sigma_threshold,
    )


def detect_model_anomalies(
    events: Iterable[UsageEvent],
    rate_card: RateCard,
    *,
    sigma_threshold: float = SESSION_SIGMA_DEFAULT,
    timezone: str = "UTC",
) -> list[Anomaly]:
    """Flag model-day combinations whose cost is unusually large for
    that model. Useful for catching a single 5-figure opus session."""
    return _score_observations(
        _model_day_observations(events, rate_card, timezone),
        sigma_threshold=sigma_threshold,
    )


def detect_project_daily_anomalies(
    events: Iterable[UsageEvent],
    rate_card: RateCard,
    timezone: str,
    *,
    sigma_threshold: float = DAILY_SIGMA_DEFAULT,
) -> list[Anomaly]:
    """Flag project-day spend spikes within each project.

    Baselines are computed inside each project and only over days where
    that project recorded spend. This avoids treating every active day
    for a sparse project as anomalous merely because the selected window
    contains inactive days.
    """
    return _score_observations(
        _project_day_observations(events, rate_card, timezone),
        sigma_threshold=sigma_threshold,
    )


@dataclass(frozen=True)
class _EfficiencyRecord:
    session_id: str
    last_seen: dt.datetime
    project: str
    model: str
    cost: float
    tokens: int
    rate: float  # USD per 1M tokens


def _session_efficiency_records(
    events: Iterable[UsageEvent], rate_card: RateCard
) -> list[_EfficiencyRecord]:
    sessions: dict[str, dict[str, object]] = {}
    for event in events:
        if not event.session_id:
            continue
        cost, _, _ = event_cost(rate_card, event)
        item = sessions.setdefault(
            event.session_id,
            {
                "last_seen": event.timestamp,
                "cost": 0.0,
                "tokens": 0,
                "projects": Counter(),
                "models": Counter(),
            },
        )
        item["last_seen"] = max(item["last_seen"], event.timestamp)  # type: ignore[arg-type]
        item["cost"] = float(item["cost"]) + float(cost.cost_usd)
        item["tokens"] = int(item["tokens"]) + int(event.usage.total_tokens)  # type: ignore[arg-type]
        item["projects"][event.thread.cwd or UNKNOWN_PROJECT] += 1  # type: ignore[index]
        item["models"][event.model or "unknown-model"] += 1  # type: ignore[index]

    records: list[_EfficiencyRecord] = []
    for session_id, item in sessions.items():
        tokens = int(item["tokens"])  # type: ignore[arg-type]
        if tokens < MIN_EFFICIENCY_TOKENS:
            continue
        cost = float(item["cost"])  # type: ignore[arg-type]
        last_seen = item["last_seen"]
        assert isinstance(last_seen, dt.datetime)
        records.append(
            _EfficiencyRecord(
                session_id=session_id,
                last_seen=last_seen,
                project=_most_common(item["projects"], UNKNOWN_PROJECT),  # type: ignore[arg-type]
                model=_most_common(item["models"], "unknown-model"),  # type: ignore[arg-type]
                cost=cost,
                tokens=tokens,
                rate=cost / (tokens / 1_000_000),
            )
        )
    return records


def detect_efficiency_regressions(
    events: Iterable[UsageEvent],
    rate_card: RateCard,
    *,
    sigma_threshold: float = EFFICIENCY_SIGMA,
) -> list[Anomaly]:
    """Flag sessions that cost more PER 1M TOKENS than their cohort's norm.

    Cohort = (project, model). Only sessions above ``MIN_EFFICIENCY_TOKENS``
    are judged (small sessions have noisy rates), and each is compared only to
    PRIOR sessions in its cohort (expanding window), so this never flags the
    first few sessions of a new cohort. The deviation is expressed back in
    dollars (``observed`` = actual cost, ``baseline`` = what that token volume
    would have cost at the cohort-typical rate) so it renders in the same
    dollar-denominated row as the other detectors and the impact is real money.
    """
    by_cohort: dict[tuple[str, str], list[_EfficiencyRecord]] = {}
    for record in _session_efficiency_records(events, rate_card):
        by_cohort.setdefault((record.project, record.model), []).append(record)

    anomalies: list[Anomaly] = []
    for (project, model), records in by_cohort.items():
        prior_rates: list[float] = []
        for record in sorted(records, key=lambda r: (r.last_seen, r.session_id)):
            if len(prior_rates) >= MIN_EFFICIENCY_COHORT:
                center = statistics.median(prior_rates)
                deviations = sorted(abs(rate - center) for rate in prior_rates)
                mad = _median_of_sorted(deviations)
                scale = max(mad * 1.4826, EFFICIENCY_SCALE_FLOOR_FRAC * center)
                if scale > 0 and record.rate > center:
                    z = (record.rate - center) / scale
                    expected_cost = center * (record.tokens / 1_000_000)
                    impact = record.cost - expected_cost
                    if z >= sigma_threshold and impact >= MIN_IMPACT_USD:
                        anomalies.append(
                            Anomaly(
                                kind="efficiency_regression",
                                timestamp=record.last_seen,
                                label=record.session_id,
                                observed=record.cost,
                                baseline_center=expected_cost,
                                baseline_scale=scale * (record.tokens / 1_000_000),
                                z_score=min(z, SIGMA_DISPLAY_CAP),
                                impact_usd_exact=Decimal(str(max(0.0, impact))),
                                comparison_scope=(
                                    "prior sessions of similar size in same project/model"
                                ),
                                baseline_sample_count=len(prior_rates),
                                cohort_key="\0".join(("efficiency", project, model)),
                                cohort_label=f"{project} / {model}",
                                reason=(
                                    f"${record.rate:,.2f} per 1M tokens vs "
                                    f"${center:,.2f} typical for this cohort "
                                    f"({z:.1f}σ over {len(prior_rates)} prior sessions)"
                                ),
                                dedupe_key=f"efficiency:{record.session_id}",
                                impact_percent=_impact_percent(record.rate, center),
                            )
                        )
            bisect.insort(prior_rates, record.rate)
    return sorted(anomalies, key=_sort_key)


__all__ = [
    "ACTIVE_DAY_THRESHOLD",
    "DAILY_SIGMA_DEFAULT",
    "FOLD_CHANGE_MIN",
    "MIN_IMPACT_USD",
    "MIN_SAMPLES_FOR_DETECTION",
    "SESSION_SIGMA_DEFAULT",
    "SIGMA_DISPLAY_CAP",
    "detect_actionable_anomalies",
    "detect_daily_anomalies",
    "detect_efficiency_regressions",
    "detect_model_anomalies",
    "detect_project_daily_anomalies",
    "detect_session_anomalies",
    "human_label",
]
