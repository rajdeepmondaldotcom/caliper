from __future__ import annotations

from caliper.subscriptions import (
    normalize_subscription_plan,
    subscription_cost_caveat,
    subscription_plan_payload,
    subscription_warnings,
)


def test_subscription_plan_normalization_covers_codex_plan_families() -> None:
    assert normalize_subscription_plan("ChatGPT Plus") == "plus"
    assert normalize_subscription_plan("team") == "business"
    assert normalize_subscription_plan("education") == "edu"
    assert normalize_subscription_plan("Pro $100") == "pro_100"
    assert normalize_subscription_plan("ChatGPT for Teachers") == "teachers"


def test_subscription_payload_marks_known_and_promotional_plans() -> None:
    payload = subscription_plan_payload({"free", "pro", "enterprise", "mystery"})
    by_slug = {item["slug"]: item for item in payload}

    assert by_slug["free"]["limited_time_access"] is True
    assert by_slug["pro"]["known"] is True
    assert by_slug["enterprise"]["enterprise_family"] is True
    assert by_slug["mystery"]["known"] is False


def test_subscription_warnings_surface_only_real_ambiguity() -> None:
    assert subscription_warnings({"plus", "business"}) == []

    warnings = subscription_warnings({"go", "enterprise", "unexpected"})

    assert any("Free/Go" in warning for warning in warnings)
    assert any("legacy rate card" in warning for warning in warnings)
    assert any("Unknown Codex subscription plan" in warning for warning in warnings)


def test_subscription_cost_caveat_labels_known_plans_as_api_equivalent() -> None:
    caveat = subscription_cost_caveat({"pro"})
    assert caveat is not None
    assert "ChatGPT Pro" in caveat
    assert "API-equivalent" in caveat
    # No recognized plan (metered API use, or nothing) → the total is the bill.
    assert subscription_cost_caveat(set()) is None
    assert subscription_cost_caveat({"totally-unknown-plan"}) is None
