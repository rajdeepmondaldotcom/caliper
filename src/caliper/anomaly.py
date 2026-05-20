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


def _mad(values: list[float], center: float) -> float:
    """Median absolute deviation. Resilient fallback when stdev is 0."""
    if not values:
        return 0.0
    deviations = sorted(abs(value - center) for value in values)
    return statistics.median(deviations)


MULT_OF_MEDIAN_TRIGGER = 5.0


def _baseline_stats(values: list[float]) -> tuple[float, float]:
    """Return ``(median, robust_scale)`` using MAD ×1.4826.

    Median + MAD is preferred over mean + pstdev so a single large
    outlier cannot inflate its own baseline. When MAD collapses to
    zero (constant baseline + outlier) the scale falls back to
    ``median / (1.4826 × MULT_OF_MEDIAN_TRIGGER)`` so any point above
    ``MULT_OF_MEDIAN_TRIGGER × median`` crosses the 1.4826σ threshold
    used by the detectors.
    """
    if len(values) < 2:
        return (values[0] if values else 0.0), 0.0
    median = statistics.median(values)
    mad = _mad(values, median)
    robust = mad * 1.4826
    if robust > 0:
        return median, robust
    if median > 0:
        return median, median / MULT_OF_MEDIAN_TRIGGER
    sigma = statistics.pstdev(values)
    return median, sigma


def _z(value: float, mean: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    return (value - mean) / scale


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
        z = _z(cost, center, scale)
        if z < sigma_threshold:
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
        z = _z(observed, center, scale)
        if z < sigma_threshold:
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
            z = _z(cost, center, scale)
            if z < sigma_threshold:
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
            z = _z(cost, center, scale)
            if z < sigma_threshold:
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
    "DAILY_SIGMA_DEFAULT",
    "MIN_SAMPLES_FOR_DETECTION",
    "SESSION_SIGMA_DEFAULT",
    "detect_daily_anomalies",
    "detect_model_anomalies",
    "detect_project_daily_anomalies",
    "detect_session_anomalies",
]
