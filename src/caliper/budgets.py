"""Budgets and threshold-based alerts.

Pure-function evaluation. Reads `.caliper.toml` `[budgets]` tables via the
CLI layer; this module just takes Budget dataclasses + a usage dict and emits
BudgetAlert results.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from caliper.aggregation import aggregate_total
from caliper.models import LoadResult, RuntimeOptions, decimal_string
from caliper.pricing import RateCard
from caliper.timeutil import iso_z

VALID_PERIODS = ("daily", "weekly", "monthly")
VALID_METRICS = ("cost_usd", "tokens")
SEVERITY_OK = "ok"
SEVERITY_WARN = "warn"
SEVERITY_BREACH = "breach"
SEVERITY_ORDER = (SEVERITY_OK, SEVERITY_WARN, SEVERITY_BREACH)
SEVERITY_EXIT_CODE = {SEVERITY_OK: 0, SEVERITY_WARN: 1, SEVERITY_BREACH: 2}


@dataclass(frozen=True)
class Budget:
    period: str
    metric: str
    limit: float
    warn_at: float = 0.8

    def key(self) -> str:
        return f"{self.period}.{self.metric}"


@dataclass(frozen=True)
class BudgetAlert:
    budget: Budget
    used: float
    used_percent: float
    severity: str


def severity_for(used_percent: float, warn_at_percent: float) -> str:
    if used_percent >= 100.0:
        return SEVERITY_BREACH
    if used_percent >= warn_at_percent * 100.0:
        return SEVERITY_WARN
    return SEVERITY_OK


def evaluate(budgets: list[Budget], usage: dict[str, Any]) -> list[BudgetAlert]:
    """Score each budget against the matching usage value. Missing usage → 0."""
    alerts: list[BudgetAlert] = []
    for budget in budgets:
        _validate_budget(budget)
        used = float(usage.get(budget.key(), 0.0))
        used_percent = used / budget.limit * 100.0
        alerts.append(
            BudgetAlert(
                budget=budget,
                used=used,
                used_percent=used_percent,
                severity=severity_for(used_percent, budget.warn_at),
            )
        )
    return alerts


def current_period_intervals(now: dt.datetime) -> dict[str, tuple[dt.datetime, dt.datetime]]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - dt.timedelta(days=day_start.weekday())
    month_start = day_start.replace(day=1)
    return {
        "daily": (day_start, now),
        "weekly": (week_start, now),
        "monthly": (month_start, now),
    }


def usage_for_periods(
    events,
    options: RuntimeOptions,
    rate_card: RateCard,
    now: dt.datetime,
    windows: dict[str, tuple[dt.datetime, dt.datetime]] | None = None,
) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    for period, (start, end) in (windows or current_period_intervals(now)).items():
        scoped = [event for event in events if start <= event.timestamp < end]
        result = LoadResult(
            events=scoped,
            duplicates=0,
            tier_sources={},
            plan_types=set(),
            rate_limit_samples=[],
            warnings=[],
        )
        aggregate = aggregate_total(result, options, label=period, rate_card=rate_card)
        usage[f"{period}.cost_usd"] = aggregate.costs.cost_usd
        usage[f"{period}.tokens"] = float(aggregate.totals.total_tokens)
    return usage


def alert_records(
    alerts: list[BudgetAlert],
    usage: dict[str, Any],
    pricing_status: str,
    windows: dict[str, tuple[dt.datetime, dt.datetime]] | None = None,
) -> list[dict]:
    records = []
    for alert in alerts:
        record = {
            "period": alert.budget.period,
            "metric": alert.budget.metric,
            "limit": alert.budget.limit,
            "warn_at": alert.budget.warn_at,
            "used": alert.used,
            "used_exact": decimal_string(usage.get(alert.budget.key(), alert.used)),
            "used_percent": round(alert.used_percent, 2),
            "used_percent_exact": decimal_string(alert.used_percent),
            "severity": alert.severity,
            "pricing_status": pricing_status,
        }
        if windows and alert.budget.period in windows:
            start, end = windows[alert.budget.period]
            record.update(
                {
                    "window_start": iso_z(start),
                    "window_end": iso_z(end),
                    "window_label": f"{alert.budget.period} to date",
                }
            )
        records.append(record)
    return records


def max_severity(alerts: list[BudgetAlert]) -> str:
    if not alerts:
        return SEVERITY_OK
    worst = SEVERITY_OK
    for alert in alerts:
        if SEVERITY_ORDER.index(alert.severity) > SEVERITY_ORDER.index(worst):
            worst = alert.severity
    return worst


def serialize_budgets(budgets: list[Budget]) -> dict:
    """Inverse of :func:`parse_budgets_table`.

    Emits the explicit ``{"items": [...]}`` shape so the output is
    unambiguous regardless of how the user originally wrote their
    config. ``parse_budgets_table(serialize_budgets(budgets))`` must
    equal ``budgets``.
    """
    return {
        "items": [
            {
                "period": budget.period,
                "metric": budget.metric,
                "limit": float(budget.limit),
                "warn_at": float(budget.warn_at),
            }
            for budget in budgets
        ]
    }


def parse_budgets_table(table: dict) -> list[Budget]:
    """Convert a parsed TOML `[budgets]` table into a list of Budget dataclasses.

    Recognized shapes:
    - {"daily_cost_usd": 25.00}
    - {"daily": {"cost_usd": 5.0, "warn_at": 0.9}}
    - {"items": [{"period": "daily", "metric": "cost_usd", "limit": 25.00}]}
    """
    if not table:
        return []

    if "items" in table and isinstance(table["items"], list):
        return [_budget_from_dict(item) for item in table["items"]]

    budgets: list[Budget] = []
    for key, value in table.items():
        budgets.extend(_budgets_from_table_entry(key, value))
    return budgets


def _budgets_from_table_entry(key: str, value: object) -> list[Budget]:
    if isinstance(value, dict) and key in VALID_PERIODS:
        return _nested_budgets(key, value)
    if isinstance(value, (int, float)):
        budget = _flat_budget(key, value)
        return [budget] if budget is not None else []
    return []


def _nested_budgets(period: str, value: dict) -> list[Budget]:
    warn_at = float(value.get("warn_at", 0.8))
    return [
        _budget(period=period, metric=metric, limit=float(limit), warn_at=warn_at)
        for metric, limit in value.items()
        if metric in VALID_METRICS
    ]


def _flat_budget(key: str, value: float) -> Budget | None:
    period, metric = _split_flat_key(key)
    if not period or not metric:
        return None
    return _budget(period=period, metric=metric, limit=float(value))


def _split_flat_key(key: str) -> tuple[str, str]:
    parts = key.split("_", 1)
    if len(parts) != 2:
        return "", ""
    period, metric = parts
    if period not in VALID_PERIODS or metric not in VALID_METRICS:
        return "", ""
    return period, metric


def _budget_from_dict(raw: dict) -> Budget:
    period = str(raw["period"])
    metric = str(raw["metric"])
    limit = float(raw["limit"])
    warn_at = float(raw.get("warn_at", 0.8))
    if period not in VALID_PERIODS:
        raise ValueError(f"unknown budget period {period!r}; expected {VALID_PERIODS}")
    if metric not in VALID_METRICS:
        raise ValueError(f"unknown budget metric {metric!r}; expected {VALID_METRICS}")
    return _budget(period=period, metric=metric, limit=limit, warn_at=warn_at)


def _budget(*, period: str, metric: str, limit: float, warn_at: float = 0.8) -> Budget:
    budget = Budget(period=period, metric=metric, limit=limit, warn_at=warn_at)
    _validate_budget(budget)
    return budget


def _validate_budget(budget: Budget) -> None:
    if budget.limit <= 0:
        raise ValueError(f"budget {budget.key()} limit must be greater than 0")
    if not 0 < budget.warn_at < 1:
        raise ValueError(f"budget {budget.key()} warn_at must be greater than 0 and less than 1")
