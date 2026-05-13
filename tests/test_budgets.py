from __future__ import annotations

import pytest

from caliper.budgets import (
    SEVERITY_BREACH,
    SEVERITY_OK,
    SEVERITY_WARN,
    Budget,
    evaluate,
    max_severity,
    parse_budgets_table,
    severity_for,
)


def test_severity_classification() -> None:
    assert severity_for(0.0, 0.8) == SEVERITY_OK
    assert severity_for(50.0, 0.8) == SEVERITY_OK
    assert severity_for(79.9, 0.8) == SEVERITY_OK
    assert severity_for(80.0, 0.8) == SEVERITY_WARN
    assert severity_for(99.9, 0.8) == SEVERITY_WARN
    assert severity_for(100.0, 0.8) == SEVERITY_BREACH
    assert severity_for(150.0, 0.8) == SEVERITY_BREACH


def test_evaluate_pairs_budgets_with_usage() -> None:
    budgets = [
        Budget(period="daily", metric="credits", limit=1000.0),
        Budget(period="weekly", metric="credits", limit=5000.0, warn_at=0.9),
    ]
    usage = {"daily.credits": 850.0, "weekly.credits": 5200.0}
    alerts = evaluate(budgets, usage)
    assert alerts[0].severity == SEVERITY_WARN
    assert pytest.approx(alerts[0].used_percent, rel=1e-6) == 85.0
    assert alerts[1].severity == SEVERITY_BREACH


def test_evaluate_missing_usage_treats_as_zero() -> None:
    budgets = [Budget(period="daily", metric="credits", limit=100.0)]
    alerts = evaluate(budgets, {})
    assert alerts[0].used == 0.0
    assert alerts[0].severity == SEVERITY_OK


def test_zero_limit_produces_zero_percent() -> None:
    budgets = [Budget(period="daily", metric="credits", limit=0.0)]
    alerts = evaluate(budgets, {"daily.credits": 999.0})
    assert alerts[0].used_percent == 0.0
    assert alerts[0].severity == SEVERITY_OK


def test_max_severity_picks_worst() -> None:
    budgets = [
        Budget(period="daily", metric="credits", limit=100.0),
        Budget(period="weekly", metric="credits", limit=200.0),
    ]
    usage_ok = {"daily.credits": 10, "weekly.credits": 20}
    usage_warn = {"daily.credits": 90, "weekly.credits": 20}
    usage_breach = {"daily.credits": 90, "weekly.credits": 250}
    assert max_severity(evaluate(budgets, usage_ok)) == SEVERITY_OK
    assert max_severity(evaluate(budgets, usage_warn)) == SEVERITY_WARN
    assert max_severity(evaluate(budgets, usage_breach)) == SEVERITY_BREACH


def test_parse_flat_keys() -> None:
    table = {"daily_credits": 25000, "weekly_api_dollars": 50.0}
    parsed = parse_budgets_table(table)
    by_key = {budget.key(): budget for budget in parsed}
    assert by_key["daily.credits"].limit == 25000.0
    assert by_key["weekly.api_dollars"].limit == 50.0


def test_parse_nested_period_dict_with_warn_at() -> None:
    table = {"monthly": {"credits": 500000, "api_dollars": 100.0, "warn_at": 0.7}}
    parsed = parse_budgets_table(table)
    by_key = {budget.key(): budget for budget in parsed}
    assert by_key["monthly.credits"].warn_at == 0.7
    assert by_key["monthly.api_dollars"].warn_at == 0.7


def test_parse_items_list_form() -> None:
    table = {
        "items": [
            {"period": "daily", "metric": "credits", "limit": 25000},
            {"period": "weekly", "metric": "tokens", "limit": 1_000_000, "warn_at": 0.95},
        ]
    }
    parsed = parse_budgets_table(table)
    assert {budget.key() for budget in parsed} == {"daily.credits", "weekly.tokens"}


def test_parse_items_rejects_unknown_metric() -> None:
    table = {"items": [{"period": "daily", "metric": "minutes", "limit": 10}]}
    with pytest.raises(ValueError):
        parse_budgets_table(table)


def test_parse_silently_skips_unknown_flat_keys() -> None:
    table = {"nonsense_key": 5, "daily_credits": 10}
    parsed = parse_budgets_table(table)
    assert [budget.key() for budget in parsed] == ["daily.credits"]
