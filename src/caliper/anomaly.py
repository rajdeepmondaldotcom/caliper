"""Statistical anomaly detection over usage events.

Pure stdlib. Returns :class:`Anomaly` records carrying both the σ
distance from baseline and the dollar impact of the deviation so the
dashboard can present a single, ranked "what stands out" list.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Iterable
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
    per_session: dict[str, tuple[dt.datetime, float]] = {}
    for event in events:
        if not event.session_id:
            continue
        cost, _, _ = event_cost(rate_card, event)
        existing = per_session.get(event.session_id)
        new_cost = float(cost.cost_usd) + (existing[1] if existing else 0.0)
        last_seen = event.timestamp
        if existing and existing[0] > last_seen:
            last_seen = existing[0]
        per_session[event.session_id] = (last_seen, new_cost)
    if len(per_session) < MIN_SAMPLES_FOR_DETECTION:
        return []

    costs = [cost for _ts, cost in per_session.values()]
    center, scale = _baseline_stats(costs)
    if scale <= 0:
        return []

    anomalies: list[Anomaly] = []
    for session_id, (ts, cost) in per_session.items():
        ok, z = _qualifies(cost, center, scale, sigma_threshold)
        if not ok:
            continue
        impact = Decimal(str(max(0.0, cost - center)))
        anomalies.append(
            Anomaly(
                kind="session_spike",
                timestamp=ts,
                label=session_id,
                observed=cost,
                baseline_center=center,
                baseline_scale=scale,
                z_score=z,
                impact_usd_exact=impact,
            )
        )
    return sorted(anomalies, key=lambda a: -a.z_score)


def detect_daily_anomalies(
    daily: list[Aggregate],
    *,
    sigma_threshold: float = DAILY_SIGMA_DEFAULT,
) -> list[Anomaly]:
    """Flag day-level cost spikes."""
    if len(daily) < MIN_SAMPLES_FOR_DETECTION:
        return []
    costs = [float(row.costs.cost_usd) for row in daily]
    center, scale = _baseline_stats(costs)
    if scale <= 0:
        return []
    anomalies: list[Anomaly] = []
    for row in daily:
        observed = float(row.costs.cost_usd)
        ok, z = _qualifies(observed, center, scale, sigma_threshold)
        if not ok:
            continue
        impact = Decimal(str(max(0.0, observed - center)))
        timestamp = row.last_seen or row.first_seen or dt.datetime.now(tz=dt.UTC)
        anomalies.append(
            Anomaly(
                kind="daily_spike",
                timestamp=timestamp,
                label=row.label,
                observed=observed,
                baseline_center=center,
                baseline_scale=scale,
                z_score=z,
                impact_usd_exact=impact,
            )
        )
    return sorted(anomalies, key=lambda a: -a.z_score)


def detect_model_anomalies(
    events: Iterable[UsageEvent],
    rate_card: RateCard,
    *,
    sigma_threshold: float = SESSION_SIGMA_DEFAULT,
) -> list[Anomaly]:
    """Flag model-day combinations whose cost is unusually large for
    that model. Useful for catching a single 5-figure opus session."""
    per_model_day: dict[tuple[str, dt.date], tuple[dt.datetime, float]] = {}
    for event in events:
        if not event.model:
            continue
        cost, _, _ = event_cost(rate_card, event)
        day = event.timestamp.date()
        key = (event.model, day)
        seen, total = per_model_day.get(key, (event.timestamp, 0.0))
        per_model_day[key] = (
            max(seen, event.timestamp),
            total + float(cost.cost_usd),
        )

    by_model: dict[str, list[tuple[dt.date, dt.datetime, float]]] = {}
    for (model, day), (ts, cost) in per_model_day.items():
        by_model.setdefault(model, []).append((day, ts, cost))

    anomalies: list[Anomaly] = []
    for model, rows in by_model.items():
        if len(rows) < MIN_SAMPLES_FOR_DETECTION:
            continue
        costs = [cost for _d, _ts, cost in rows]
        center, scale = _baseline_stats(costs)
        if scale <= 0:
            continue
        for day, ts, cost in rows:
            ok, z = _qualifies(cost, center, scale, sigma_threshold)
            if not ok:
                continue
            anomalies.append(
                Anomaly(
                    kind="model_day_spike",
                    timestamp=ts,
                    label=f"{model} / {day.isoformat()}",
                    observed=cost,
                    baseline_center=center,
                    baseline_scale=scale,
                    z_score=z,
                    impact_usd_exact=Decimal(str(max(0.0, cost - center))),
                )
            )
    return sorted(anomalies, key=lambda a: -a.z_score)


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
    tz = load_timezone(timezone)
    per_project_day: dict[tuple[str, dt.date], tuple[dt.datetime, float]] = {}
    for event in events:
        project = event.thread.cwd or UNKNOWN_PROJECT
        day = event.timestamp.astimezone(tz).date()
        key = (project, day)
        seen, total = per_project_day.get(key, (event.timestamp, 0.0))
        cost, _, _ = event_cost(rate_card, event)
        per_project_day[key] = (
            max(seen, event.timestamp),
            total + float(cost.cost_usd),
        )

    by_project: dict[str, list[tuple[dt.date, dt.datetime, float]]] = {}
    for (project, day), (ts, cost) in per_project_day.items():
        by_project.setdefault(project, []).append((day, ts, cost))

    anomalies: list[Anomaly] = []
    for project, rows in by_project.items():
        if len(rows) < MIN_SAMPLES_FOR_DETECTION:
            continue
        costs = [cost for _day, _ts, cost in rows]
        center, scale = _baseline_stats(costs)
        if scale <= 0:
            continue
        for day, ts, cost in rows:
            ok, z = _qualifies(cost, center, scale, sigma_threshold)
            if not ok:
                continue
            anomalies.append(
                Anomaly(
                    kind="project_day_spike",
                    timestamp=ts,
                    label=f"{project} / {day.isoformat()}",
                    observed=cost,
                    baseline_center=center,
                    baseline_scale=scale,
                    z_score=z,
                    impact_usd_exact=Decimal(str(max(0.0, cost - center))),
                )
            )
    return sorted(anomalies, key=lambda a: -a.z_score)


__all__ = [
    "ACTIVE_DAY_THRESHOLD",
    "DAILY_SIGMA_DEFAULT",
    "FOLD_CHANGE_MIN",
    "MIN_IMPACT_USD",
    "MIN_SAMPLES_FOR_DETECTION",
    "SESSION_SIGMA_DEFAULT",
    "SIGMA_DISPLAY_CAP",
    "detect_daily_anomalies",
    "detect_model_anomalies",
    "detect_project_daily_anomalies",
    "detect_session_anomalies",
]
