"""Statistical anomaly detection over usage events.

Pure stdlib. Returns :class:`Anomaly` records carrying both the σ
distance from baseline and the dollar impact of the deviation so the
dashboard can present a single, ranked "what stands out" list.
"""

from __future__ import annotations

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


def _mad(values: list[float], center: float) -> float:
    """Median absolute deviation. Resilient fallback when stdev is 0."""
    if not values:
        return 0.0
    deviations = sorted(abs(value - center) for value in values)
    return statistics.median(deviations)


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
    """
    if len(values) < MIN_SAMPLES_FOR_DETECTION:
        return 0.0, 0.0
    active = [v for v in values if v >= ACTIVE_DAY_THRESHOLD]
    base = active if len(active) >= MIN_SAMPLES_FOR_DETECTION else values
    median = statistics.median(base)
    mad_scale = _mad(base, median) * 1.4826
    iqr_scale = 0.0
    if len(base) >= 4:
        # ``method="exclusive"`` matches the classic Tukey quartile
        # definition (linear interpolation between order statistics)
        # and avoids degenerate cases for very small samples.
        q1, _q2, q3 = statistics.quantiles(base, n=4, method="exclusive")
        iqr_scale = max(0.0, (q3 - q1) / 1.349)
    # 1.0 floor: σ is meaningless once scale drops below a dollar; this
    # converts "huge σ on sparse data" into a bounded one-dollar gate.
    return median, max(mad_scale, iqr_scale, median * 0.10, 1.0)


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


def _sort_key(item: Anomaly) -> tuple[Decimal, float, str, str]:
    return (-item.impact_usd_exact, -item.z_score, item.kind, item.label)


def _most_common(counter: Counter[str], fallback: str) -> str:
    if not counter:
        return fallback
    value, _count = counter.most_common(1)[0]
    return value or fallback


def _scope_reason(observed: float, center: float, sample_count: int) -> str:
    fold = observed / max(center, ACTIVE_DAY_THRESHOLD)
    return f"{fold:.1f}x typical across {sample_count} comparable observations"


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
        prior_values: list[float] = []
        for row in sorted(rows, key=lambda r: (r.order, r.timestamp, r.label)):
            center, scale = _baseline_stats(prior_values)
            if scale > 0:
                ok, z = _qualifies(row.observed, center, scale, sigma_threshold)
                if ok:
                    impact = Decimal(str(max(0.0, row.observed - center)))
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
                            baseline_sample_count=len(prior_values),
                            cohort_key=row.cohort_key,
                            cohort_label=row.cohort_label,
                            reason=_scope_reason(row.observed, center, len(prior_values)),
                            dedupe_key=row.dedupe_key,
                        )
                    )
            prior_values.append(row.observed)
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


def _dedupe_anomalies(items: Iterable[Anomaly]) -> list[Anomaly]:
    by_key: dict[str, Anomaly] = {}
    for item in items:
        key = item.dedupe_key or f"{item.kind}:{item.label}"
        existing = by_key.get(key)
        if existing is None or _sort_key(item) < _sort_key(existing):
            by_key[key] = item
    return sorted(by_key.values(), key=_sort_key)


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
    "detect_model_anomalies",
    "detect_project_daily_anomalies",
    "detect_session_anomalies",
]
