from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from codex_meter import __version__
from codex_meter.pricing import MODEL_CARDS, MODELS_BY_NAME, PRICING_SOURCES, normalize_model
from codex_meter.timeutil import iso_z

ALLOWED_RATE_SOURCE_SCHEMES = {"http", "https"}


def fetched_rates_path() -> Path:
    override = os.environ.get("CODEX_METER_DATA_DIR")
    if override:
        return Path(override).expanduser() / "rates-fetched.json"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "codex-meter" / "rates-fetched.json"
    return Path.home() / ".local" / "share" / "codex-meter" / "rates-fetched.json"


def fetch_rate_sources() -> dict:
    sources = []
    observed = []
    for source in PRICING_SOURCES:
        try:
            url = _validated_source_url(source.url)
        except ValueError as exc:
            sources.append(
                {"name": source.name, "url": source.url, "status": "error", "error": str(exc)}
            )
            continue

        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"codex-meter/{__version__}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
                body = response.read()
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
    }


def rate_card_records(payload: dict) -> list[dict]:
    return [
        {
            "model": card["name"],
            "fast_multiplier": card["fast_multiplier"],
            "api_input": (card["api"] or {}).get("input", ""),
            "credits_input": (card["credits"] or {}).get("input", ""),
        }
        for card in payload["models"]
    ]


def embedded_rate_snapshot() -> list[dict]:
    return [
        {
            "name": card.name,
            "api": rates_payload(card.api_rates),
            "credits": rates_payload(card.credit_rates),
            "fast_multiplier": card.fast_multiplier,
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


def rate_discrepancies(observed_models: list[dict]) -> list[dict]:
    discrepancies: list[dict] = []
    for observed in observed_models:
        card = MODELS_BY_NAME.get(normalize_model(str(observed.get("name") or "")))
        if card is None:
            continue
        for section, rates in (("api", card.api_rates), ("credits", card.credit_rates)):
            if not rates or not isinstance(observed.get(section), dict):
                continue
            expected = rates_payload(rates) or {}
            for field in ("input", "cached_input", "output"):
                actual = observed[section].get(field)
                if actual is None:
                    continue
                if abs(float(actual) - float(expected[field])) > 1e-9:
                    discrepancies.append(
                        {
                            "model": card.name,
                            "section": section,
                            "field": field,
                            "embedded": expected[field],
                            "observed": actual,
                        }
                    )
        if observed.get("fast_multiplier") is not None:
            actual_fast = float(observed["fast_multiplier"])
            if abs(actual_fast - float(card.fast_multiplier)) > 1e-9:
                discrepancies.append(
                    {
                        "model": card.name,
                        "section": "fast_multiplier",
                        "field": "multiplier",
                        "embedded": card.fast_multiplier,
                        "observed": actual_fast,
                    }
                )
        if isinstance(observed.get("long_context"), dict) and card.long_context is not None:
            expected_long = {
                "threshold": card.long_context.threshold,
                "input_mult": card.long_context.input_mult,
                "output_mult": card.long_context.output_mult,
            }
            for field, expected in expected_long.items():
                actual = observed["long_context"].get(field)
                if actual is not None and abs(float(actual) - float(expected)) > 1e-9:
                    discrepancies.append(
                        {
                            "model": card.name,
                            "section": "long_context",
                            "field": field,
                            "embedded": expected,
                            "observed": actual,
                        }
                    )
    return discrepancies


def _validated_source_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ALLOWED_RATE_SOURCE_SCHEMES or not parsed.netloc:
        raise ValueError(f"unsupported rate source URL: {url}")
    return url


def _extract_models_from_html(text: str) -> list[dict]:
    normalized = _normal_text(text)
    found: list[dict] = []
    for card in MODEL_CARDS:
        window = _window_for_model(normalized, card.name)
        if not window:
            continue
        api_rates = _extract_api_rates(window)
        credit_rates = _extract_credit_rates(window, card.name)
        fast_multiplier = _extract_fast_multiplier(window, card.name)
        long_context = _extract_long_context_rule(window)
        item: dict = {"name": card.name}
        if api_rates:
            item["api"] = api_rates
        if credit_rates:
            item["credits"] = credit_rates
        if fast_multiplier is not None:
            item["fast_multiplier"] = fast_multiplier
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
        if "per 1m tokens" in lowered or "credits" in lowered:
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


def _extract_credit_rates(window: str, model: str) -> dict | None:
    display = re.escape(model.replace("gpt", "GPT"))
    match = re.search(
        rf"{display}\s+([0-9.]+)\s+credits\s+([0-9.]+)\s+credits\s+([0-9.]+)\s+credits",
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


def _extract_fast_multiplier(window: str, model: str) -> float | None:
    display = re.escape(model.replace("gpt", "GPT"))
    patterns = [
        rf"([0-9.]+)x\s+the\s+Standard\s+rate\s+for\s+{display}",
        rf"{display}[^.]*?([0-9.]+)x\s+the\s+Standard\s+rate",
    ]
    for pattern in patterns:
        match = re.search(pattern, window, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _extract_long_context_rule(window: str) -> dict | None:
    lowered = window.lower()
    if ">272k" not in lowered or "2x input" not in lowered or "1.5x output" not in lowered:
        return None
    return {"threshold": 272_000, "input_mult": 2.0, "output_mult": 1.5}
