from __future__ import annotations

import datetime as dt

import pytest

from caliper.budgets import (
    SEVERITY_BREACH,
    SEVERITY_OK,
    SEVERITY_WARN,
    Budget,
    alert_records,
    current_period_intervals,
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
        Budget(period="daily", metric="cost_usd", limit=1000.0),
        Budget(period="weekly", metric="cost_usd", limit=5000.0, warn_at=0.9),
    ]
    usage = {"daily.cost_usd": 850.0, "weekly.cost_usd": 5200.0}
    alerts = evaluate(budgets, usage)
    assert alerts[0].severity == SEVERITY_WARN
    assert pytest.approx(alerts[0].used_percent, rel=1e-6) == 85.0
    assert alerts[1].severity == SEVERITY_BREACH


def test_evaluate_missing_usage_treats_as_zero() -> None:
    budgets = [Budget(period="daily", metric="cost_usd", limit=100.0)]
    alerts = evaluate(budgets, {})
    assert alerts[0].used == 0.0
    assert alerts[0].severity == SEVERITY_OK


def test_zero_limit_produces_zero_percent() -> None:
    budgets = [Budget(period="daily", metric="cost_usd", limit=0.0)]
    alerts = evaluate(budgets, {"daily.cost_usd": 999.0})
    assert alerts[0].used_percent == 0.0
    assert alerts[0].severity == SEVERITY_OK


def test_max_severity_picks_worst() -> None:
    budgets = [
        Budget(period="daily", metric="cost_usd", limit=100.0),
        Budget(period="weekly", metric="cost_usd", limit=200.0),
    ]
    usage_ok = {"daily.cost_usd": 10, "weekly.cost_usd": 20}
    usage_warn = {"daily.cost_usd": 90, "weekly.cost_usd": 20}
    usage_breach = {"daily.cost_usd": 90, "weekly.cost_usd": 250}
    assert max_severity(evaluate(budgets, usage_ok)) == SEVERITY_OK
    assert max_severity(evaluate(budgets, usage_warn)) == SEVERITY_WARN
    assert max_severity(evaluate(budgets, usage_breach)) == SEVERITY_BREACH


def test_parse_flat_keys() -> None:
    table = {"daily_cost_usd": 25000, "weekly_cost_usd": 50.0}
    parsed = parse_budgets_table(table)
    by_key = {budget.key(): budget for budget in parsed}
    assert by_key["daily.cost_usd"].limit == 25000.0
    assert by_key["weekly.cost_usd"].limit == 50.0


def test_parse_nested_period_dict_with_warn_at() -> None:
    table = {"monthly": {"cost_usd": 100.0, "tokens": 500000, "warn_at": 0.7}}
    parsed = parse_budgets_table(table)
    by_key = {budget.key(): budget for budget in parsed}
    assert by_key["monthly.cost_usd"].warn_at == 0.7
    assert by_key["monthly.tokens"].warn_at == 0.7


def test_parse_items_list_form() -> None:
    table = {
        "items": [
            {"period": "daily", "metric": "cost_usd", "limit": 25000},
            {"period": "weekly", "metric": "tokens", "limit": 1_000_000, "warn_at": 0.95},
        ]
    }
    parsed = parse_budgets_table(table)
    assert {budget.key() for budget in parsed} == {"daily.cost_usd", "weekly.tokens"}


def test_parse_items_rejects_unknown_metric() -> None:
    table = {"items": [{"period": "daily", "metric": "minutes", "limit": 10}]}
    with pytest.raises(ValueError):
        parse_budgets_table(table)


def test_parse_silently_skips_unknown_flat_keys() -> None:
    table = {"nonsense_key": 5, "daily_cost_usd": 10}
    parsed = parse_budgets_table(table)
    assert [budget.key() for budget in parsed] == ["daily.cost_usd"]


def test_serialize_budgets_round_trips_through_parse_budgets_table():
    from caliper.budgets import Budget, parse_budgets_table, serialize_budgets

    budgets = [
        Budget(period="daily", metric="cost_usd", limit=25_000.0, warn_at=0.9),
        Budget(period="weekly", metric="cost_usd", limit=12.5, warn_at=0.8),
        Budget(period="monthly", metric="tokens", limit=1_000_000.0, warn_at=0.7),
    ]
    table = serialize_budgets(budgets)
    assert parse_budgets_table(table) == budgets


def test_serialize_budgets_empty_returns_items_list():
    from caliper.budgets import serialize_budgets

    assert serialize_budgets([]) == {"items": []}


def test_alert_records_include_current_period_windows() -> None:
    now = dt.datetime(2026, 5, 15, 10, 30, tzinfo=dt.UTC)
    budgets = [Budget(period="daily", metric="cost_usd", limit=100.0)]
    usage = {"daily.cost_usd": 25.0}
    alerts = evaluate(budgets, usage)
    records = alert_records(alerts, usage, "exact", windows=current_period_intervals(now))

    assert records[0]["window_start"] == "2026-05-15T00:00:00Z"
    assert records[0]["window_end"] == "2026-05-15T10:30:00Z"
    assert records[0]["window_label"] == "daily to date"


def test_alert_records_quantize_percent_but_keep_exact() -> None:
    budgets = [Budget(period="daily", metric="cost_usd", limit=3.0)]
    usage = {"daily.cost_usd": 1.0}
    records = alert_records(evaluate(budgets, usage), usage, "exact")

    assert records[0]["used_percent"] == 33.33
    assert records[0]["used_percent_exact"].startswith("33.333333")
