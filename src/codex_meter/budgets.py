"""Budgets and threshold-based alerts.

Pure-function evaluation. Reads `.codex-meter.toml` `[budgets]` tables via the
CLI layer; this module just takes Budget dataclasses + a usage dict and emits
BudgetAlert results.
"""

from __future__ import annotations

from dataclasses import dataclass

VALID_PERIODS = ("daily", "weekly", "monthly")
VALID_METRICS = ("credits", "api_dollars", "tokens")
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


def evaluate(budgets: list[Budget], usage: dict[str, float]) -> list[BudgetAlert]:
    """Score each budget against the matching usage value. Missing usage → 0."""
    alerts: list[BudgetAlert] = []
    for budget in budgets:
        used = float(usage.get(budget.key(), 0.0))
        used_percent = 0.0 if budget.limit <= 0 else used / budget.limit * 100.0
        alerts.append(
            BudgetAlert(
                budget=budget,
                used=used,
                used_percent=used_percent,
                severity=severity_for(used_percent, budget.warn_at),
            )
        )
    return alerts


def max_severity(alerts: list[BudgetAlert]) -> str:
    if not alerts:
        return SEVERITY_OK
    worst = SEVERITY_OK
    for alert in alerts:
        if SEVERITY_ORDER.index(alert.severity) > SEVERITY_ORDER.index(worst):
            worst = alert.severity
    return worst


def parse_budgets_table(table: dict) -> list[Budget]:
    """Convert a parsed TOML `[budgets]` table into a list of Budget dataclasses.

    Recognized shapes:
    - {"daily_credits": 25000, "weekly_dollars": 12.50}
    - {"daily": {"credits": 25000, "api_dollars": 5.0, "warn_at": 0.9}}
    - {"items": [{"period": "daily", "metric": "credits", "limit": 25000}]}
    """
    if not table:
        return []

    if "items" in table and isinstance(table["items"], list):
        return [_budget_from_dict(item) for item in table["items"]]

    budgets: list[Budget] = []
    for key, value in table.items():
        if isinstance(value, dict) and key in VALID_PERIODS:
            warn_at = float(value.get("warn_at", 0.8))
            for metric, limit in value.items():
                if metric == "warn_at":
                    continue
                if metric in VALID_METRICS:
                    budgets.append(
                        Budget(
                            period=key,
                            metric=metric,
                            limit=float(limit),
                            warn_at=warn_at,
                        )
                    )
            continue
        if not isinstance(value, (int, float)):
            continue
        period, metric = _split_flat_key(key)
        if period and metric:
            budgets.append(Budget(period=period, metric=metric, limit=float(value)))
    return budgets


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
    return Budget(period=period, metric=metric, limit=limit, warn_at=warn_at)
