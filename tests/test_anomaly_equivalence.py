"""Byte-identical equivalence oracle for the anomaly perf rewrite.

The anomaly engine is correctness-critical and ships in an irreversible
release, so the performance rewrite of ``_score_observations`` /
``_baseline_stats`` must produce output that is *identical* to the previous
implementation — same ``z_score``, ``baseline_center``, ``baseline_scale``,
``impact_usd_exact``, ``reason``, ordering, and dedupe.

This module freezes a verbatim copy of the previous algorithm as the
``_legacy_*`` oracle and asserts the live implementation matches it, both
on a directed corpus (sparse, zero-inflated, constant, tied, large, the
active/full boundary) and under Hypothesis. Captured against the v0.0.58
implementation before the rewrite landed; it must stay green after.
"""

from __future__ import annotations

import datetime as dt
import statistics
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from caliper import anomaly
from caliper.anomaly import (
    ACTIVE_DAY_THRESHOLD,
    MIN_SAMPLES_FOR_DETECTION,
    SESSION_SIGMA_DEFAULT,
    _Observation,
    _qualifies,
    _scope_reason,
    _sort_key,
)
from caliper.models import Anomaly

# ---------------------------------------------------------------------------
# Frozen legacy oracle — verbatim copy of the v0.0.58 algorithm.
# DO NOT "tidy" these to call the live code; they exist to be independent.
# ---------------------------------------------------------------------------


def _legacy_mad(values: list[float], center: float) -> float:
    if not values:
        return 0.0
    deviations = sorted(abs(value - center) for value in values)
    return statistics.median(deviations)


def _legacy_baseline_stats(values: list[float]) -> tuple[float, float]:
    if len(values) < MIN_SAMPLES_FOR_DETECTION:
        return 0.0, 0.0
    active = [v for v in values if v >= ACTIVE_DAY_THRESHOLD]
    base = active if len(active) >= MIN_SAMPLES_FOR_DETECTION else values
    median = statistics.median(base)
    mad_scale = _legacy_mad(base, median) * 1.4826
    iqr_scale = 0.0
    if len(base) >= 4:
        q1, _q2, q3 = statistics.quantiles(base, n=4, method="exclusive")
        iqr_scale = max(0.0, (q3 - q1) / 1.349)
    return median, max(mad_scale, iqr_scale, median * 0.10, 1.0)


def _legacy_score_observations(
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
            center, scale = _legacy_baseline_stats(prior_values)
            if scale > 0:
                ok, z = _qualifies(row.observed, center, scale, sigma_threshold)
                if ok:
                    impact = Decimal(str(max(0.0, row.observed - center)))
                    impact_percent = anomaly._impact_percent(row.observed, center)
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
                            reason=_scope_reason(
                                row.observed,
                                center,
                                len(prior_values),
                                impact_percent,
                            ),
                            dedupe_key=row.dedupe_key,
                            impact_percent=impact_percent,
                        )
                    )
            prior_values.append(row.observed)
    return sorted(anomalies, key=_sort_key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TS = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)


def _observations(values: list[float], *, cohort: str = "c1") -> list[_Observation]:
    """One cohort of session-style observations from a value series."""
    out: list[_Observation] = []
    for i, value in enumerate(values):
        ts = _BASE_TS + dt.timedelta(hours=i)
        out.append(
            _Observation(
                kind="session_spike",
                timestamp=ts,
                order=(i, f"s{i}"),
                label=f"s{i}",
                observed=value,
                cohort_key=cohort,
                cohort_label="cohort",
                comparison_scope="prior sessions in same cohort",
                dedupe_key=f"session:s{i}",
            )
        )
    return out


# Directed corpora that exercise every branch the audit doc cares about.
_DIRECTED_CASES: dict[str, list[float]] = {
    "empty": [],
    "below_min_samples": [1.0, 2.0, 3.0],
    "constant": [5.0, 5.0, 5.0, 5.0, 5.0],
    "zero_inflated": [0.0] * 30 + [307.87],
    "sparse_pennies": [0.001, 0.002, 0.0, 0.0, 0.005, 500.0],
    "active_full_boundary_3": [0.02, 0.03, 0.04, 0.0, 0.0],  # only 3 active
    "active_full_boundary_4": [0.02, 0.03, 0.04, 0.05, 0.0],  # 4 active
    "tied_values": [2.0, 2.0, 2.0, 2.0, 2.0, 50.0, 50.0],
    "ramp": [float(i) for i in range(1, 40)],
    "big_spike_late": [1.0, 1.1, 0.9, 1.05, 1.2, 0.95, 1.0, 1.0, 250.0],
    "large": [float(i % 7) + 0.5 for i in range(1000)] + [999.0],
}


def test_baseline_stats_matches_legacy_on_directed_corpus():
    for name, values in _DIRECTED_CASES.items():
        # Compare at every prefix length to mirror the expanding window.
        for k in range(len(values) + 1):
            prefix = values[:k]
            assert anomaly._baseline_stats(prefix) == _legacy_baseline_stats(prefix), (
                f"{name} @ prefix {k}"
            )


def test_score_observations_matches_legacy_on_directed_corpus():
    for name, values in _DIRECTED_CASES.items():
        obs = _observations(values)
        live = anomaly._score_observations(obs, sigma_threshold=SESSION_SIGMA_DEFAULT)
        legacy = _legacy_score_observations(obs, sigma_threshold=SESSION_SIGMA_DEFAULT)
        assert live == legacy, name


def test_session_detection_matches_legacy_with_multiple_cohorts():
    # Two interleaved cohorts to exercise per-cohort baselines.
    obs = _observations(_DIRECTED_CASES["big_spike_late"], cohort="a") + _observations(
        _DIRECTED_CASES["zero_inflated"], cohort="b"
    )
    live = anomaly._score_observations(obs, sigma_threshold=SESSION_SIGMA_DEFAULT)
    legacy = _legacy_score_observations(obs, sigma_threshold=SESSION_SIGMA_DEFAULT)
    assert live == legacy


_value = st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False)
# Bias toward ties and the active/full threshold — the riskiest float paths.
_tricky = st.sampled_from([0.0, 0.005, 0.01, 0.011, 1.0, 1.0, 2.5, 250.0])


@settings(max_examples=400, deadline=None)
@given(st.lists(_value, min_size=0, max_size=120))
def test_baseline_stats_property_equivalence(values: list[float]):
    assert anomaly._baseline_stats(values) == _legacy_baseline_stats(values)


@settings(max_examples=400, deadline=None)
@given(st.lists(_tricky, min_size=0, max_size=60))
def test_baseline_stats_property_equivalence_ties(values: list[float]):
    assert anomaly._baseline_stats(values) == _legacy_baseline_stats(values)


@settings(max_examples=300, deadline=None)
@given(st.lists(_value, min_size=0, max_size=80))
def test_score_observations_property_equivalence(values: list[float]):
    obs = _observations(values)
    live = anomaly._score_observations(obs, sigma_threshold=SESSION_SIGMA_DEFAULT)
    legacy = _legacy_score_observations(obs, sigma_threshold=SESSION_SIGMA_DEFAULT)
    assert live == legacy


@settings(max_examples=300, deadline=None)
@given(st.lists(_tricky, min_size=0, max_size=60))
def test_score_observations_property_equivalence_ties(values: list[float]):
    obs = _observations(values)
    live = anomaly._score_observations(obs, sigma_threshold=SESSION_SIGMA_DEFAULT)
    legacy = _legacy_score_observations(obs, sigma_threshold=SESSION_SIGMA_DEFAULT)
    assert live == legacy


def test_human_label_is_plain_english():
    # Normal multiple → an "≈Nx" gloss a non-engineer understands.
    assert anomaly.human_label(50.0, 10.0, 5.0) == "≈5× your typical spend for this cohort"
    # At the σ cap (near-zero baseline) → "extreme", never an absurd multiplier.
    extreme = anomaly.human_label(307.88, 0.08, anomaly.SIGMA_DISPLAY_CAP)
    assert "extreme" in extreme
    assert "×" not in extreme
    # Huge-but-uncapped fold collapses to a phrase, not "≈4000×".
    assert "×" not in anomaly.human_label(1000.0, 1.0, 10.0)
    # Near-zero baseline (below the active threshold) → phrase, no division.
    assert "near-zero" in anomaly.human_label(5.0, 0.0, 8.0)


def test_sparse_data_sigma_stays_bounded():
    # The 354,210σ regression guard: a huge spike against near-zero baseline
    # must clamp to the display cap, not explode.
    obs = _observations([0.0] * 30 + [307.87])
    out = anomaly._score_observations(obs, sigma_threshold=SESSION_SIGMA_DEFAULT)
    assert out
    assert all(a.z_score <= anomaly.SIGMA_DISPLAY_CAP for a in out)
