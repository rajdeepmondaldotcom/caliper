"""Forecast helpers: linear and EWMA projection, confidence band.

Pure functions over a list of per-day numeric samples (credits, dollars, tokens —
unit-agnostic). I/O lives in the CLI layer.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

DEFAULT_EWMA_ALPHA = 0.3


@dataclass(frozen=True)
class Projection:
    unit: str
    days_analyzed: int
    daily_mean: float
    daily_stdev: float
    days_remaining: int
    linear_total: float
    ewma_total: float
    linear_low: float
    linear_high: float
    cap: float | None
    days_to_cap: float | None


def daily_mean(daily_values: list[float]) -> float:
    if not daily_values:
        return 0.0
    return statistics.fmean(daily_values)


def daily_stdev(daily_values: list[float]) -> float:
    if len(daily_values) < 2:
        return 0.0
    return statistics.pstdev(daily_values)


def ewma(daily_values: list[float], alpha: float = DEFAULT_EWMA_ALPHA) -> float:
    """Exponentially-weighted moving average. Newer days weighted more heavily."""
    if not daily_values:
        return 0.0
    if not 0 < alpha <= 1:
        raise ValueError("ewma alpha must be in (0, 1]")
    smoothed = daily_values[0]
    for value in daily_values[1:]:
        smoothed = alpha * value + (1 - alpha) * smoothed
    return smoothed


def project(
    daily_values: list[float],
    days_remaining: int,
    *,
    unit: str = "credits",
    cap: float | None = None,
    alpha: float = DEFAULT_EWMA_ALPHA,
) -> Projection:
    """Project the rolling-sum total `days_remaining` days into the future.

    `linear_total` uses the simple mean; `ewma_total` uses an exponentially
    weighted mean that reacts faster to recent acceleration.
    """
    if days_remaining < 0:
        raise ValueError("days_remaining must be non-negative")
    mean = daily_mean(daily_values)
    sigma = daily_stdev(daily_values)
    ewma_rate = ewma(daily_values, alpha)
    linear_total = mean * days_remaining
    ewma_total = ewma_rate * days_remaining
    # 1σ band scales with sqrt(N) under iid assumption.
    band = sigma * math.sqrt(days_remaining) if days_remaining > 0 else 0.0
    days_to_cap: float | None = None
    if cap is not None and mean > 0:
        days_to_cap = max(0.0, cap / mean)
    return Projection(
        unit=unit,
        days_analyzed=len(daily_values),
        daily_mean=mean,
        daily_stdev=sigma,
        days_remaining=days_remaining,
        linear_total=linear_total,
        ewma_total=ewma_total,
        linear_low=max(0.0, linear_total - band),
        linear_high=linear_total + band,
        cap=cap,
        days_to_cap=days_to_cap,
    )
