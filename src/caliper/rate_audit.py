"""Rate-card audit helpers.

This module is split into two surfaces:

- **Offline (read-only)** helpers — `rate_card_payload`,
  `rate_card_records`, `embedded_rate_snapshot`, `billing_calculation_checks`
  — used by `caliper rates show` and `caliper rates catalog` without any
  network access.
- **Online (opt-in)** helpers — `fetch_rate_sources()` — performs the
  audit-research workflow against published rate cards. All network I/O
  routes through `caliper.network.fetch_bytes`, which is the single
  chokepoint guarded by `--allow-network` at the CLI boundary. The
  function exists for the test suite and future audit-CLI use; the
  default code path never invokes it.

Both surfaces share the same internal helpers so the embedded rate card
and the audit output share one source of truth.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from pathlib import Path

from caliper.models import Usage, decimal_string
from caliper.network import CALIPER_USER_AGENT, fetch_bytes, validate_source_url
from caliper.pricing import (
    MODEL_CARDS,
    MODELS_BY_NAME,
    PRICING_SOURCES,
    RateCard,
    normalize_model,
)
from caliper.timeutil import iso_z

ALLOWED_RATE_SOURCE_SCHEMES = {"http", "https"}


def fetched_rates_path() -> Path:
    override = os.environ.get("CALIPER_DATA_DIR")
    if override:
        return Path(override).expanduser() / "rates-fetched.json"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "caliper" / "rates-fetched.json"
    return Path.home() / ".local" / "share" / "caliper" / "rates-fetched.json"


def fetch_rate_sources() -> dict:
    sources: list[dict[str, object]] = []
    observed: list[dict] = []
    for source in PRICING_SOURCES:
        try:
            url = _validated_source_url(source.url)
        except ValueError as exc:
            sources.append(
                {"name": source.name, "url": source.url, "status": "error", "error": str(exc)}
            )
            continue

        try:
            body = fetch_bytes(
                url,
                allowed_schemes=ALLOWED_RATE_SOURCE_SCHEMES,
                source_kind="rate source",
                user_agents=(CALIPER_USER_AGENT,),
            )
        except OSError as exc:
            sources.append(
                {"name": source.name, "url": source.url, "status": "error", "error": str(exc)}
            )
            continue
        text = body.decode("utf-8", errors="replace")
        extracted = extract_models_from_text(text)
        sources.append(
            {
                "name": source.name,
                "url": source.url,
                "status": "ok",
                "bytes": len(body),
                "observed_models": len(extracted),
            }
        )
        observed.extend(item | {"source": source.name} for item in extracted)
    observed_models = dedupe_models(observed)
    return {
        "fetched_at": iso_z(dt.datetime.now(tz=dt.UTC)),
        "sources": sources,
        "embedded_models": embedded_rate_snapshot(),
        "observed_models": observed_models,
        "models": observed_models,
        "discrepancies": rate_discrepancies(observed_models),
    }


def extract_models_from_text(text: str) -> list[dict]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return _extract_models_from_html(text)
    if isinstance(raw, dict) and isinstance(raw.get("models"), list):
        return [item for item in raw["models"] if isinstance(item, dict) and item.get("name")]
    return []


def dedupe_models(models: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for model in models:
        name = str(model["name"])
        merged = deduped.setdefault(name, {"name": name})
        for key, value in model.items():
            if key == "name":
                continue
            if key == "source" and merged.get("source") and merged["source"] != value:
                merged["source"] = f"{merged['source']}; {value}"
                continue
            merged[key] = value
    return [deduped[key] for key in sorted(deduped)]


def rates_payload(rates) -> dict | None:
    if rates is None:
        return None
    return {
        "input": float(rates.input),
        "cached_input": float(rates.cached_input),
        "output": float(rates.output),
        "reasoning_output": float(rates.effective_reasoning_output),
        "cache_creation_input": (
            float(rates.cache_creation_input) if rates.cache_creation_input is not None else None
        ),
        "cache_creation_input_1h": (
            float(rates.cache_creation_input_1h)
            if rates.cache_creation_input_1h is not None
            else None
        ),
    }


def rate_card_payload(age_days: int) -> dict:
    return {
        "checked": [
            {"name": source.name, "url": source.url, "checked": source.checked}
            for source in PRICING_SOURCES
        ],
        "age_days": age_days,
        "stale": age_days > 90,
        "models": embedded_rate_snapshot(),
        "billing_checks": billing_calculation_checks(),
    }


def rate_card_records(payload: dict) -> list[dict]:
    return [
        {
            "model": card["name"],
            "api_input": (card["api"] or {}).get("input", ""),
        }
        for card in payload["models"]
    ]


def embedded_rate_snapshot() -> list[dict]:
    return [
        {
            "name": card.name,
            "api": rates_payload(card.api_rates),
            "long_context": (
                {
                    "threshold": card.long_context.threshold,
                    "input_mult": card.long_context.input_mult,
                    "output_mult": card.long_context.output_mult,
                }
                if card.long_context
                else None
            ),
        }
        for card in MODEL_CARDS
    ]


def billing_calculation_checks() -> list[dict[str, object]]:
    card = RateCard.load(None, "model")
    scenarios = [
        {
            "name": "gpt-5.5 fast long-context",
            "model": "gpt-5.5",
            "tier": "fast",
            "usage": Usage(
                input_tokens=1_000_000,
                cached_input_tokens=500_000,
                output_tokens=100_000,
                reasoning_output_tokens=25_000,
                total_tokens=1_100_000,
            ),
            "expected_cost_usd": "25",
            "expected_long_context": True,
        },
        {
            "name": "gpt-5.4 threshold boundary",
            "model": "gpt-5.4",
            "tier": "standard",
            "usage": Usage(input_tokens=272_000, output_tokens=1_000, total_tokens=273_000),
            "expected_cost_usd": "0.695",
            "expected_long_context": False,
        },
        {
            "name": "gpt-5.4 over threshold",
            "model": "gpt-5.4",
            "tier": "standard",
            "usage": Usage(input_tokens=272_001, output_tokens=1_000, total_tokens=273_001),
            "expected_cost_usd": "1.382505",
            "expected_long_context": True,
        },
        {
            "name": "gpt-5.3-codex cache split",
            "model": "gpt-5.3-codex",
            "tier": "standard",
            "usage": Usage(
                input_tokens=10_000,
                cached_input_tokens=4_000,
                output_tokens=1_000,
                total_tokens=11_000,
            ),
            "expected_cost_usd": "0.0252",
            "expected_long_context": False,
        },
    ]
    return [_billing_calculation_check(card, scenario) for scenario in scenarios]


def _billing_calculation_check(card: RateCard, scenario: dict[str, object]) -> dict[str, object]:
    usage = scenario["usage"]
    if not isinstance(usage, Usage):
        raise TypeError("billing calculation scenarios must provide Usage instances")
    model = str(scenario["model"])
    tier = str(scenario["tier"])
    cost, long_context, unknown_model = card.cost_for(usage, model, tier)
    actual = {
        "cost_usd": decimal_string(cost.cost_usd),
        "long_context": long_context,
        "unknown_model": unknown_model,
    }
    expected = {
        "cost_usd": scenario["expected_cost_usd"],
        "long_context": scenario["expected_long_context"],
        "unknown_model": False,
    }
    return {
        "name": scenario["name"],
        "model": model,
        "tier": tier,
        "passed": actual == expected,
        "expected": expected,
        "actual": actual,
    }


def rate_discrepancies(observed_models: list[dict]) -> list[dict]:
    discrepancies: list[dict] = []
    for observed in observed_models:
        card = MODELS_BY_NAME.get(normalize_model(str(observed.get("name") or "")))
        if card is not None:
            discrepancies.extend(_model_rate_discrepancies(card, observed))
    return discrepancies


def _model_rate_discrepancies(card, observed: dict) -> list[dict]:
    return [
        *_section_rate_discrepancies(card, observed, "api", card.api_rates),
        *_long_context_discrepancies(card, observed),
    ]


def _section_rate_discrepancies(card, observed: dict, section: str, rates) -> list[dict]:
    observed_rates = observed.get(section)
    if not rates or not isinstance(observed_rates, dict):
        return []
    expected = rates_payload(rates) or {}
    discrepancies: list[dict] = []
    for field in ("input", "cached_input", "output"):
        actual = observed_rates.get(field)
        if actual is not None and _different_number(actual, expected[field]):
            discrepancies.append(
                {
                    "model": card.name,
                    "section": section,
                    "field": field,
                    "embedded": expected[field],
                    "observed": actual,
                }
            )
    return discrepancies


def _long_context_discrepancies(card, observed: dict) -> list[dict]:
    observed_long = observed.get("long_context")
    if not isinstance(observed_long, dict) or card.long_context is None:
        return []
    expected_long = {
        "threshold": card.long_context.threshold,
        "input_mult": card.long_context.input_mult,
        "output_mult": card.long_context.output_mult,
    }
    return [
        {
            "model": card.name,
            "section": "long_context",
            "field": field,
            "embedded": expected,
            "observed": actual,
        }
        for field, expected in expected_long.items()
        if (actual := observed_long.get(field)) is not None and _different_number(actual, expected)
    ]


def _different_number(left, right) -> bool:
    return abs(float(left) - float(right)) > 1e-9


def _validated_source_url(url: str) -> str:
    return validate_source_url(
        url,
        allowed_schemes=ALLOWED_RATE_SOURCE_SCHEMES,
        source_kind="rate source",
    )


def _extract_models_from_html(text: str) -> list[dict]:
    normalized = _normal_text(text)
    found: list[dict] = []
    for card in MODEL_CARDS:
        window = _window_for_model(normalized, card.name)
        if not window:
            continue
        api_rates = _extract_api_rates(window)
        long_context = _extract_long_context_rule(window)
        item: dict = {"name": card.name}
        if api_rates:
            item["api"] = api_rates
        if long_context is not None:
            item["long_context"] = long_context
        if len(item) > 1:
            found.append(item)
    return found


def _normal_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u2011", "-").replace("\u2010", "-").replace("\u2013", "-")
    text = text.replace("\u2014", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _window_for_model(text: str, model: str) -> str:
    candidates = [
        text[max(0, match.start() - 1000) : match.start() + 3500]
        for match in re.finditer(re.escape(model), text, flags=re.IGNORECASE)
    ]
    for candidate in candidates:
        lowered = candidate.lower()
        if "per 1m tokens" in lowered:
            return candidate
    return candidates[0] if candidates else ""


def _extract_api_rates(window: str) -> dict | None:
    match = re.search(
        r"Per 1M tokens\s+Input\s+\$([0-9.]+)\s+Cached input\s+\$([0-9.]+)\s+Output\s+\$([0-9.]+)",
        window,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "input": float(match.group(1)),
        "cached_input": float(match.group(2)),
        "output": float(match.group(3)),
    }


def _extract_long_context_rule(window: str) -> dict | None:
    lowered = window.lower()
    if ">272k" not in lowered or "2x input" not in lowered or "1.5x output" not in lowered:
        return None
    return {"threshold": 272_000, "input_mult": 2.0, "output_mult": 1.5}
