"""Predictive analytics.

Per-model demand forecasts (OLS slope), seasonality decomposition,
rate-limit exhaustion forecasts with confidence bands, project burn
projections. Pure stdlib — uses :mod:`statistics` and :mod:`math`.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections.abc import Iterable

from caliper.aggregation import event_cost
from caliper.forecasts import Projection, project
from caliper.models import (
    Aggregate,
    LoadResult,
    ModelDemandForecast,
    RateLimitForecast,
    RateLimitSample,
    RuntimeOptions,
    SeasonalityProfile,
    UsageEvent,
)
from caliper.patterns import (
    hour_dow_buckets,
    per_model_daily_tokens,
)
from caliper.pricing import RateCard, model_vendor
from caliper.timeutil import load_timezone
from caliper.windows import BURN_RATE_LOOKBACK_HOURS, compute_window_state

MIN_OLS_POINTS = 4
DEFAULT_HORIZON_DAYS = 30


def linear_slope(points: list[tuple[float, float]]) -> float:
    """OLS slope. Returns 0.0 for under-sampled input (<4 points) and
    for series with zero x-variance."""
    if len(points) < MIN_OLS_POINTS:
        return 0.0
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in points)
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def _dense_daily_series(
    daily: dict[dt.date, float],
    start: dt.date,
    end: dt.date,
) -> list[float]:
    """Project a sparse {date: value} dict onto every day in
    [start, end] (inclusive). Missing days fill with 0.0."""
    if start > end:
        return []
    days = (end - start).days + 1
    series = [0.0] * days
    for day, value in daily.items():
        if start <= day <= end:
            series[(day - start).days] = float(value)
    return series


def forecast_per_model(
    events: Iterable[UsageEvent],
    rate_card: RateCard,
    timezone: str,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> list[ModelDemandForecast]:
    """Forecast token demand per model from daily token series.

    Each model gets an OLS trend slope over the analysed window, a daily
    mean/stdev for tokens, and a 30-day cost projection priced through
    ``rate_card``. Models with fewer than :data:`MIN_OLS_POINTS` days of
    data still receive a row — slope falls to 0.0 and ``growing`` is
    ``False`` so the caller can present a stable surface.
    """
    events_list = list(events)
    if not events_list:
        return []
    tz = load_timezone(timezone)
    days_per_model = per_model_daily_tokens(events_list, timezone)
    if not days_per_model:
        return []
    all_dates = sorted({day for model_days in days_per_model.values() for day in model_days})
    start, end = all_dates[0], all_dates[-1]

    cost_per_model = _per_model_daily_cost(events_list, rate_card, tz)
    total_projected = 0.0
    cards: list[tuple[ModelDemandForecast, float]] = []
    for model in sorted(days_per_model):
        token_series = _dense_daily_series(
            {day: float(value) for day, value in days_per_model[model].items()},
            start,
            end,
        )
        cost_series = _dense_daily_series(cost_per_model.get(model, {}), start, end)
        mean_tokens = statistics.fmean(token_series) if token_series else 0.0
        stdev_tokens = statistics.pstdev(token_series) if len(token_series) > 1 else 0.0
        slope = linear_slope(list(enumerate(token_series, start=1)))
        mean_cost = statistics.fmean(cost_series) if cost_series else 0.0
        projected_cost = mean_cost * horizon_days
        cards.append(
            (
                ModelDemandForecast(
                    model=model,
                    model_vendor=model_vendor(model),
                    days_analyzed=len(token_series),
                    daily_mean_tokens=mean_tokens,
                    daily_stdev_tokens=stdev_tokens,
                    trend_slope_tokens_per_day=slope,
                    projected_share_30d=0.0,
                    growing=slope > 0,
                    daily_mean_cost_usd=mean_cost,
                    projected_cost_30d_usd=projected_cost,
                ),
                projected_cost,
            )
        )
        total_projected += projected_cost

    if total_projected <= 0:
        return [card for card, _ in cards]
    return [
        ModelDemandForecast(
            model=card.model,
            model_vendor=card.model_vendor,
            days_analyzed=card.days_analyzed,
            daily_mean_tokens=card.daily_mean_tokens,
            daily_stdev_tokens=card.daily_stdev_tokens,
            trend_slope_tokens_per_day=card.trend_slope_tokens_per_day,
            projected_share_30d=cost / total_projected,
            growing=card.growing,
            daily_mean_cost_usd=card.daily_mean_cost_usd,
            projected_cost_30d_usd=card.projected_cost_30d_usd,
        )
        for card, cost in cards
    ]


def _per_model_daily_cost(
    events: list[UsageEvent],
    rate_card: RateCard,
    tz: dt.tzinfo,
) -> dict[str, dict[dt.date, float]]:
    result: dict[str, dict[dt.date, float]] = {}
    for event in events:
        if not event.model:
            continue
        cost, _, _ = event_cost(rate_card, event)
        local = event.timestamp.astimezone(tz).date()
        bucket = result.setdefault(event.model, {})
        bucket[local] = bucket.get(local, 0.0) + float(cost.cost_usd)
    return result


def decompose_seasonality(
    events: Iterable[UsageEvent],
    rate_card: RateCard,
    timezone: str,
) -> SeasonalityProfile:
    """Decompose spend by hour-of-day + day-of-week in local TZ.

    ``off_peak_share`` reports the fraction of cost that fell in the
    lower-spend half of hours. It does not imply cheaper vendor pricing.
    """

    def cost_for(event: UsageEvent) -> float:
        cost, _, _ = event_cost(rate_card, event)
        return float(cost.cost_usd)

    by_hour, by_dow = hour_dow_buckets(events, timezone, cost_fn=cost_for)
    total = sum(by_hour)
    if total <= 0:
        return SeasonalityProfile(
            by_hour_cost_usd=tuple(by_hour),
            by_dow_cost_usd=tuple(by_dow),
            peak_hour=0,
            peak_dow=0,
            off_peak_share=0.0,
            timezone=timezone,
        )
    peak_hour = max(range(24), key=lambda h: by_hour[h])
    peak_dow = max(range(7), key=lambda d: by_dow[d])
    sorted_hours = sorted(by_hour)
    bottom_half = sum(sorted_hours[:12])
    off_peak = bottom_half / total if total else 0.0
    return SeasonalityProfile(
        by_hour_cost_usd=tuple(by_hour),
        by_dow_cost_usd=tuple(by_dow),
        peak_hour=peak_hour,
        peak_dow=peak_dow,
        off_peak_share=off_peak,
        timezone=timezone,
    )


def forecast_rate_limits(
    samples: list[RateLimitSample],
    now: dt.datetime | None = None,
) -> list[RateLimitForecast]:
    """Per-window rate-limit exhaustion forecast with confidence band.

    A high-confidence forecast requires ≥5 samples within the burn-rate
    lookback window; medium needs ≥3; otherwise the function returns
    ``None`` for the ETA fields and marks confidence as ``low``.
    """
    if not samples:
        return []
    now = now or _latest_sample_timestamp(samples)
    forecasts: list[RateLimitForecast] = []
    for window in ("primary", "secondary"):
        state = compute_window_state(samples, now, window)
        if state.samples == 0:
            continue
        burn = state.burn_rate_per_hour
        used = state.used_percent
        eta_mid = _hours_to_full(used, burn)
        confidence = _confidence(state.samples, burn)
        sigma = _burn_rate_stdev(samples, window, state.limit_id)
        eta_low, eta_high = _eta_band(used, burn, sigma)
        forecasts.append(
            RateLimitForecast(
                window=window,
                limit_id=state.limit_id,
                limit_name=state.limit_name,
                current_percent=used,
                burn_rate_per_hour=burn,
                eta_to_100_hours=eta_mid,
                eta_low_hours=eta_low,
                eta_high_hours=eta_high,
                confidence=confidence,
                samples=state.samples,
            )
        )
    return forecasts


def _latest_sample_timestamp(samples: list[RateLimitSample]) -> dt.datetime:
    return max(sample.timestamp for sample in samples)


def _burn_rate_stdev(samples: list[RateLimitSample], window: str, limit_id: str) -> float:
    selected = [sample for sample in samples if not limit_id or sample.limit_id == limit_id]
    if not selected:
        selected = list(samples)
    ordered = sorted(selected, key=lambda sample: sample.timestamp)
    if len(ordered) < 3:
        return 0.0
    latest = ordered[-1]
    cutoff = latest.timestamp - dt.timedelta(hours=BURN_RATE_LOOKBACK_HOURS)
    recent = [sample for sample in ordered if sample.timestamp >= cutoff]
    rates: list[float] = []
    previous = recent[0] if recent else None
    for sample in recent[1:]:
        if previous is None:
            previous = sample
            continue
        previous_pct = getattr(previous, f"{window}_used_percent", None)
        current_pct = getattr(sample, f"{window}_used_percent", None)
        elapsed = (sample.timestamp - previous.timestamp).total_seconds() / 3600.0
        if previous_pct is not None and current_pct is not None and elapsed > 0:
            rates.append((float(current_pct) - float(previous_pct)) / elapsed)
        previous = sample
    if len(rates) < 2:
        return 0.0
    return statistics.pstdev(rates)


def _hours_to_full(used: float | None, burn: float | None) -> float | None:
    if used is None or burn is None or burn <= 0 or used >= 100:
        return None
    return (100.0 - used) / burn


def _eta_band(
    used: float | None,
    burn: float | None,
    sigma: float,
) -> tuple[float | None, float | None]:
    mid = _hours_to_full(used, burn)
    if mid is None or burn is None or burn <= 0:
        return None, None
    lower_rate = max(burn - sigma, burn * 0.5)
    upper_rate = burn + sigma
    high = (100.0 - used) / lower_rate if lower_rate > 0 else None
    low = (100.0 - used) / upper_rate if upper_rate > 0 else None
    return low, high


def _confidence(samples: int, burn: float | None) -> str:
    if burn is None:
        return "low"
    if samples >= 5:
        return "high"
    if samples >= 3:
        return "medium"
    return "low"


def forecast_project_burn(
    projects: list[Aggregate],
    options: RuntimeOptions,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    daily_factory=None,
) -> dict[str, Projection]:
    """Per-project linear+EWMA spend projection.

    Returns ``{project_label: Projection}`` for projects with at least
    3 days of activity. Sparse projects are omitted so the caller does
    not show wild bands.
    """
    if not projects:
        return {}
    forecasts: dict[str, Projection] = {}
    for project_row in projects:
        if daily_factory is None:
            series = _flatten_daily_cost(project_row, options)
        else:
            series = daily_factory(project_row)
        if len(series) < 3:
            continue
        forecasts[project_row.label] = project(
            series,
            horizon_days,
            unit="cost_usd",
            cap=None,
        )
    return forecasts


def _flatten_daily_cost(project_row: Aggregate, options: RuntimeOptions) -> list[float]:
    """Crude fallback when caller does not provide a daily series.

    Uses ``first_seen``/``last_seen`` to spread the project's cost over
    the active days. Best-effort: real callers should pass a precomputed
    per-project per-day series via ``daily_factory``.
    """
    if not project_row.first_seen or not project_row.last_seen:
        return []
    tz = load_timezone(options.timezone)
    start = project_row.first_seen.astimezone(tz).date()
    end = project_row.last_seen.astimezone(tz).date()
    days = max(1, (end - start).days + 1)
    daily = float(project_row.costs.cost_usd) / days
    return [daily] * days


def per_project_daily_cost(
    result: LoadResult,
    rate_card: RateCard,
    options: RuntimeOptions,
) -> dict[str, list[float]]:
    """Real per-project daily cost series. Use this as ``daily_factory``."""
    tz = load_timezone(options.timezone)
    per_project: dict[str, dict[dt.date, float]] = {}
    for event in result.events:
        project = event.thread.cwd or "unknown"
        cost, _, _ = event_cost(rate_card, event)
        local = event.timestamp.astimezone(tz).date()
        bucket = per_project.setdefault(project, {})
        bucket[local] = bucket.get(local, 0.0) + float(cost.cost_usd)

    out: dict[str, list[float]] = {}
    for project_path, by_day in per_project.items():
        if not by_day:
            continue
        start, end = min(by_day), max(by_day)
        out[project_path] = _dense_daily_series(by_day, start, end)
    return out


def total_outlook(
    series: list[float],
    *,
    horizon_30d: int = 30,
    horizon_90d: int = 90,
) -> dict[str, Projection]:
    """Stakeholder-grade 30/90-day cost outlooks. Light wrapper over
    :func:`project` to keep CLI bodies thin."""
    return {
        "30d": project(series, horizon_30d, unit="cost_usd"),
        "90d": project(series, horizon_90d, unit="cost_usd"),
    }


def safe_ratio(numerator: float, denominator: float) -> float:
    """Defensive divide. Returns 0.0 instead of raising or producing
    ``inf``/``nan``. Used to keep projection bands renderable."""
    if not denominator or math.isnan(denominator) or math.isinf(denominator):
        return 0.0
    value = numerator / denominator
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return value


__all__ = [
    "DEFAULT_HORIZON_DAYS",
    "MIN_OLS_POINTS",
    "decompose_seasonality",
    "forecast_per_model",
    "forecast_project_burn",
    "forecast_rate_limits",
    "linear_slope",
    "per_project_daily_cost",
    "safe_ratio",
    "total_outlook",
]
