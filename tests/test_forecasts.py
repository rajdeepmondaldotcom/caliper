from __future__ import annotations

import math

import pytest

from caliper.forecasts import (
    daily_mean,
    daily_stdev,
    ewma,
    project,
)


def test_empty_series_yields_zero_mean() -> None:
    assert daily_mean([]) == 0.0
    assert daily_stdev([]) == 0.0
    assert ewma([]) == 0.0


def test_single_value_is_its_own_mean_and_ewma() -> None:
    assert daily_mean([5.0]) == 5.0
    assert ewma([5.0]) == 5.0
    assert daily_stdev([5.0]) == 0.0


def test_ewma_weights_recent_more_heavily() -> None:
    rising = [1.0, 1.0, 1.0, 10.0]
    flat = [1.0, 1.0, 1.0, 1.0]
    assert ewma(rising, alpha=0.5) > ewma(flat, alpha=0.5)
    assert ewma(flat, alpha=0.5) == 1.0


def test_ewma_alpha_validated() -> None:
    with pytest.raises(ValueError):
        ewma([1.0, 2.0], alpha=0.0)
    with pytest.raises(ValueError):
        ewma([1.0, 2.0], alpha=1.5)


def test_project_linear_total_matches_mean_times_days() -> None:
    daily = [10.0] * 7
    projection = project(daily, days_remaining=14, unit="credits")
    assert projection.daily_mean == 10.0
    assert projection.linear_total == 140.0
    assert projection.ewma_total == 140.0


def test_project_band_zero_when_no_variance() -> None:
    daily = [10.0] * 5
    projection = project(daily, days_remaining=10)
    assert projection.linear_low == projection.linear_total
    assert projection.linear_high == projection.linear_total


def test_project_band_widens_with_variance() -> None:
    daily = [5.0, 15.0, 5.0, 15.0, 5.0, 15.0]
    projection = project(daily, days_remaining=10)
    assert projection.linear_high > projection.linear_total
    assert projection.linear_low < projection.linear_total
    # σ ≈ 5; band ≈ σ × √10 ≈ 15.81
    assert math.isclose(
        projection.linear_high - projection.linear_total,
        projection.daily_stdev * math.sqrt(10),
        rel_tol=1e-6,
    )


def test_project_cap_reports_days_to_depletion() -> None:
    daily = [100.0] * 7
    projection = project(daily, days_remaining=14, cap=1000.0)
    assert projection.cap == 1000.0
    assert projection.days_to_cap == 10.0  # 1000 / 100


def test_project_rejects_negative_days_remaining() -> None:
    with pytest.raises(ValueError):
        project([1.0], days_remaining=-1)


def test_project_zero_mean_yields_no_days_to_cap() -> None:
    projection = project([0.0, 0.0, 0.0], days_remaining=14, cap=500.0)
    assert projection.days_to_cap is None
