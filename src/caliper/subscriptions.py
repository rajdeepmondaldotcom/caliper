from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubscriptionPlan:
    slug: str
    label: str
    token_rate_card: bool = True
    limited_time_access: bool = False
    enterprise_family: bool = False


PLAN_CATALOG: tuple[SubscriptionPlan, ...] = (
    SubscriptionPlan("free", "ChatGPT Free", token_rate_card=False, limited_time_access=True),
    SubscriptionPlan("go", "ChatGPT Go", token_rate_card=False, limited_time_access=True),
    SubscriptionPlan("plus", "ChatGPT Plus"),
    SubscriptionPlan("pro", "ChatGPT Pro"),
    SubscriptionPlan("pro_100", "ChatGPT Pro $100"),
    SubscriptionPlan("pro_200", "ChatGPT Pro $200"),
    SubscriptionPlan("business", "ChatGPT Business"),
    SubscriptionPlan("enterprise", "ChatGPT Enterprise", enterprise_family=True),
    SubscriptionPlan("edu", "ChatGPT Edu", enterprise_family=True),
    SubscriptionPlan("health", "ChatGPT Health", enterprise_family=True),
    SubscriptionPlan("gov", "ChatGPT Gov", enterprise_family=True),
    SubscriptionPlan("teachers", "ChatGPT for Teachers", enterprise_family=True),
)

PLANS_BY_SLUG = {plan.slug: plan for plan in PLAN_CATALOG}

PLAN_ALIASES = {
    "free": "free",
    "chatgpt free": "free",
    "go": "go",
    "chatgpt go": "go",
    "plus": "plus",
    "chatgpt plus": "plus",
    "pro": "pro",
    "chatgpt pro": "pro",
    "pro 100": "pro_100",
    "pro $100": "pro_100",
    "pro_100": "pro_100",
    "pro-100": "pro_100",
    "pro100": "pro_100",
    "pro 200": "pro_200",
    "pro $200": "pro_200",
    "pro_200": "pro_200",
    "pro-200": "pro_200",
    "pro200": "pro_200",
    "business": "business",
    "chatgpt business": "business",
    "team": "business",
    "enterprise": "enterprise",
    "chatgpt enterprise": "enterprise",
    "ent": "enterprise",
    "edu": "edu",
    "education": "edu",
    "chatgpt edu": "edu",
    "health": "health",
    "chatgpt health": "health",
    "gov": "gov",
    "government": "gov",
    "chatgpt gov": "gov",
    "teacher": "teachers",
    "teachers": "teachers",
    "chatgpt for teachers": "teachers",
}


def normalize_subscription_plan(plan_type: str | None) -> str:
    raw = " ".join(str(plan_type or "").strip().lower().replace("_", " ").split())
    return PLAN_ALIASES.get(raw, raw)


def subscription_plan_payload(plan_types: set[str]) -> list[dict]:
    payload: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw in sorted(plan_types):
        slug = normalize_subscription_plan(raw)
        key = (raw, slug)
        if key in seen:
            continue
        seen.add(key)
        plan = PLANS_BY_SLUG.get(slug)
        payload.append(
            {
                "raw": raw,
                "slug": slug,
                "label": plan.label if plan else raw,
                "known": plan is not None,
                "token_rate_card": plan.token_rate_card if plan else None,
                "limited_time_access": plan.limited_time_access if plan else None,
                "enterprise_family": plan.enterprise_family if plan else None,
            }
        )
    return payload


def subscription_warnings(plan_types: set[str]) -> list[str]:
    warnings: list[str] = []
    payload = subscription_plan_payload(plan_types)
    unknown = [item["raw"] for item in payload if not item["known"]]
    if unknown:
        warnings.append(
            "Unknown Codex subscription plan type(s): "
            + ", ".join(sorted(str(item) for item in unknown))
            + ". Rate-limit percentages are still reported from local logs."
        )
    if any(item["limited_time_access"] for item in payload):
        warnings.append(
            "Free/Go Codex access is promotional; use logged rate-limit percentages as the "
            "source of truth for remaining usage."
        )
    if any(item["enterprise_family"] for item in payload):
        warnings.append(
            "Enterprise-family workspaces are usually token-priced, but a small subset can "
            "remain on a legacy rate card; confirm workspace migration if exact cost matters."
        )
    return warnings


def subscription_cost_caveat(plan_types: set[str]) -> str | None:
    """A one-line caveat to show when a known ChatGPT subscription is detected.

    Codex usage under a flat subscription is rate-limited, not billed per token,
    so the rate-card total is the **API-equivalent value** of that usage rather
    than an amount actually billed. Returns ``None`` when no recognized plan is
    present (e.g. metered API use), where the per-token total *is* the real bill.
    Pricing itself is never altered — this only labels what the number means.
    """
    known = [item for item in subscription_plan_payload(plan_types) if item["known"]]
    if not known:
        return None
    labels = ", ".join(sorted({str(item["label"]) for item in known}))
    return (
        f"Usage value, not your bill — {labels} is a flat-rate plan, so this total is the "
        "API-equivalent value of your metered usage, not an invoiced amount. "
        "Pricing is unchanged; only the label is."
    )
