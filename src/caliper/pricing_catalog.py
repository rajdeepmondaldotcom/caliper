from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from caliper.models import LongContextRule, Rates, decimal_value
from caliper.network import BROWSER_USER_AGENT, CALIPER_USER_AGENT, fetch_text
from caliper.timeutil import iso_z

CATALOG_SCHEMA_VERSION = 1
DEFAULT_TTL_HOURS = 24
ALLOWED_PRICING_SOURCES = {"auto", "portkey", "litellm", "embedded"}
ALLOWED_SOURCE_SCHEMES = {"https"}

PORTKEY_PROVIDERS = (
    "openai",
    "anthropic",
    "google",
    "openrouter",
    "github",
    "azure-openai",
    "azure-ai",
    "bedrock",
    "vertex-ai",
)
PORTKEY_BASE_URL = "https://configs.portkey.ai/pricing/{provider}.json"
PORTKEY_GITHUB_BASE_URL = (
    "https://raw.githubusercontent.com/Portkey-AI/models/main/pricing/{provider}.json"
)
LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)


@dataclass(frozen=True)
class CatalogModel:
    name: str
    provider: str
    api_rates: Rates | None = None
    long_context: LongContextRule | None = None
    context_window: int = 0
    max_output_tokens: int = 0
    source: str = ""
    source_url: str = ""
    aliases: tuple[str, ...] = ()
    additional_units: dict[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class PricingCatalog:
    fetched_at: dt.datetime | None
    source: str
    models: dict[str, CatalogModel]
    path: Path | None = None
    warnings: tuple[str, ...] = ()

    @property
    def model_count(self) -> int:
        return len({model.name for model in self.models.values()})


def pricing_catalog_path() -> Path:
    override = os.environ.get("CALIPER_DATA_DIR")
    if override:
        return Path(override).expanduser() / "rates-fetched.json"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "caliper" / "rates-fetched.json"
    return Path.home() / ".local" / "share" / "caliper" / "rates-fetched.json"


def load_cached_catalog(path: Path | None = None) -> PricingCatalog:
    target = path or pricing_catalog_path()
    try:
        payload = json.loads(target.expanduser().read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return PricingCatalog(
            fetched_at=None,
            source="cache",
            models={},
            path=target,
            warnings=(f"pricing catalog cache unavailable: {exc}",),
        )
    catalog = catalog_from_payload(payload, path=target)
    return catalog


def replace_pricing_catalog_cache(payload: dict[str, Any], path: Path | None = None) -> Path:
    """Atomically replace the cached catalog with exactly this payload.

    Refreshes intentionally do not merge with the previous cache. If a model or rate
    disappears from the live source, the next cache file drops it too.
    """
    target = (path or pricing_catalog_path()).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        os.replace(temp, target)
    finally:
        with suppress(FileNotFoundError):
            temp.unlink()
    return target


def load_pricing_catalog(
    *,
    pricing_source: str = "auto",
    ttl_hours: int = DEFAULT_TTL_HOURS,
    offline: bool = True,
    path: Path | None = None,
) -> PricingCatalog:
    source = _validate_pricing_source(pricing_source)
    if source == "embedded":
        return PricingCatalog(fetched_at=None, source="embedded", models={}, path=path)

    target = path or pricing_catalog_path()
    cached = load_cached_catalog(target)
    if offline:
        return (
            cached
            if cached.models
            else PricingCatalog(
                fetched_at=None,
                source=source,
                models={},
                path=target,
                warnings=cached.warnings,
            )
        )
    if cached.models and not catalog_is_stale(cached, ttl_hours):
        return cached

    try:
        payload = fetch_pricing_catalog(source)
    except OSError as exc:
        warnings = (*cached.warnings, f"pricing catalog refresh failed: {exc}")
        if cached.models:
            return PricingCatalog(
                fetched_at=cached.fetched_at,
                source=cached.source,
                models=cached.models,
                path=target,
                warnings=warnings,
            )
        return PricingCatalog(
            fetched_at=None,
            source=source,
            models={},
            path=target,
            warnings=warnings,
        )
    if source != "embedded" and not payload.get("models"):
        warnings = (
            *cached.warnings,
            *tuple(str(item) for item in payload.get("warnings", []) if item),
            "pricing catalog refresh returned no models",
        )
        if cached.models:
            return PricingCatalog(
                fetched_at=cached.fetched_at,
                source=cached.source,
                models=cached.models,
                path=target,
                warnings=warnings,
            )
        return PricingCatalog(
            fetched_at=None,
            source=source,
            models={},
            path=target,
            warnings=warnings,
        )

    replace_pricing_catalog_cache(payload, target)
    return catalog_from_payload(payload, path=target)


def catalog_is_stale(catalog: PricingCatalog, ttl_hours: int) -> bool:
    if catalog.fetched_at is None:
        return True
    age = dt.datetime.now(tz=dt.UTC) - catalog.fetched_at.astimezone(dt.UTC)
    return age > dt.timedelta(hours=max(0, ttl_hours))


def catalog_age_hours(catalog: PricingCatalog) -> float | None:
    if catalog.fetched_at is None:
        return None
    age = dt.datetime.now(tz=dt.UTC) - catalog.fetched_at.astimezone(dt.UTC)
    return max(0.0, age.total_seconds() / 3600)


def fetch_pricing_catalog(pricing_source: str = "auto") -> dict[str, Any]:
    source = _validate_pricing_source(pricing_source)
    if source == "embedded":
        return _empty_payload(source)

    sources: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    if source in {"auto", "portkey"}:
        portkey_records, portkey_sources = _fetch_portkey_records()
        records.extend(portkey_records)
        sources.extend(portkey_sources)

    if source in {"auto", "litellm"}:
        litellm_records, litellm_source = _fetch_litellm_records()
        records.extend(litellm_records)
        sources.append(litellm_source)

    models = _merge_model_records(records, prefer=source)
    warnings = [
        f"{item.get('name') or item.get('url') or 'pricing source'} failed: {item.get('error')}"
        for item in sources
        if item.get("status") == "error"
    ]
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "source": source,
        "fetched_at": iso_z(dt.datetime.now(tz=dt.UTC)),
        "sources": sources,
        "warnings": warnings,
        "model_count": len(models),
        "models": models,
    }


def catalog_from_payload(payload: dict[str, Any], path: Path | None = None) -> PricingCatalog:
    raw_models = payload.get("models", [])
    if not isinstance(raw_models, list):
        raw_models = []
    models: dict[str, CatalogModel] = {}
    for raw in raw_models:
        if not isinstance(raw, dict) or not raw.get("name"):
            continue
        model = _catalog_model_from_record(raw)
        for key in _model_keys(model.name, *model.aliases):
            models.setdefault(key, model)
    fetched_at = _parse_datetime(str(payload.get("fetched_at") or ""))
    return PricingCatalog(
        fetched_at=fetched_at,
        source=str(payload.get("source") or "cache"),
        models=models,
        path=path,
        warnings=tuple(str(item) for item in payload.get("warnings", []) if item),
    )


def catalog_model_records(catalog: PricingCatalog) -> list[dict[str, Any]]:
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for model in sorted(catalog.models.values(), key=lambda item: (item.provider, item.name)):
        if model.name in seen:
            continue
        seen.add(model.name)
        records.append(catalog_model_record(model))
    return records


def catalog_model_record(model: CatalogModel) -> dict[str, Any]:
    api = _rates_payload(model.api_rates)
    return {
        "provider": model.provider,
        "model": model.name,
        "api_input": (api or {}).get("input", ""),
        "api_cached_input": (api or {}).get("cached_input", ""),
        "api_output": (api or {}).get("output", ""),
        "context_window": model.context_window or "",
        "max_output_tokens": model.max_output_tokens or "",
        "source": model.source,
    }


def available_catalog_models(catalog: PricingCatalog) -> set[str]:
    return set(catalog.models)


def _fetch_portkey_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for provider in PORTKEY_PROVIDERS:
        url = PORTKEY_BASE_URL.format(provider=provider)
        try:
            raw = _fetch_json(url)
        except OSError:
            fallback_url = PORTKEY_GITHUB_BASE_URL.format(provider=provider)
            try:
                raw = _fetch_json(fallback_url)
            except OSError as exc:
                sources.append(
                    {
                        "name": f"Portkey {provider}",
                        "url": url,
                        "status": "error",
                        "error": str(exc),
                    }
                )
                continue
            url = fallback_url
        provider_records = _records_from_portkey(provider, raw, url)
        records.extend(provider_records)
        sources.append(
            {
                "name": f"Portkey {provider}",
                "url": url,
                "status": "ok",
                "models": len(provider_records),
            }
        )
    return records, sources


def _fetch_litellm_records() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        raw = _fetch_json(LITELLM_URL)
    except OSError as exc:
        return [], {
            "name": "LiteLLM model cost map",
            "url": LITELLM_URL,
            "status": "error",
            "error": str(exc),
        }
    records = _records_from_litellm(raw, LITELLM_URL)
    return records, {
        "name": "LiteLLM model cost map",
        "url": LITELLM_URL,
        "status": "ok",
        "models": len(records),
    }


def _fetch_json(url: str) -> Any:
    try:
        return json.loads(_fetch_text(url))
    except json.JSONDecodeError as exc:
        raise OSError(f"invalid JSON from {url}: {exc}") from exc


def _fetch_text(url: str) -> str:
    return fetch_text(
        url,
        allowed_schemes=ALLOWED_SOURCE_SCHEMES,
        source_kind="pricing source",
        user_agents=(CALIPER_USER_AGENT, BROWSER_USER_AGENT),
        retry_statuses={403, 429},
    )


def _records_from_portkey(provider: str, raw: Any, source_url: str) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("models"), list):
        return _generic_model_records(provider, raw["models"], "portkey", source_url)
    if not isinstance(raw, dict):
        return []
    records: list[dict[str, Any]] = []
    for name, item in raw.items():
        if name == "default" or not isinstance(item, dict):
            continue
        rates = _rates_from_portkey(item)
        if rates is None and "pricing_config" not in item:
            continue
        records.append(
            {
                "name": _clean_model_name(name),
                "provider": provider,
                "source": "portkey",
                "source_url": source_url,
                "api": _rates_payload(rates),
                "additional_units": _additional_units_from_portkey(item),
            }
        )
    return records


def _records_from_litellm(raw: Any, source_url: str) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    records: list[dict[str, Any]] = []
    for name, item in raw.items():
        if name == "sample_spec" or not isinstance(item, dict):
            continue
        rates = _rates_from_litellm(item)
        if rates is None:
            continue
        records.append(
            {
                "name": _clean_model_name(name),
                "provider": str(item.get("litellm_provider") or ""),
                "source": "litellm",
                "source_url": source_url,
                "api": _rates_payload(rates),
                "long_context": _long_context_from_litellm(item),
                "context_window": _safe_int(item.get("max_input_tokens") or item.get("max_tokens")),
                "max_output_tokens": _safe_int(item.get("max_output_tokens")),
            }
        )
    return records


def _generic_model_records(
    provider: str, raw_models: list[Any], source: str, source_url: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in raw_models:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        rates = None
        if {"input", "output"} <= set(item):
            cached = item.get("cached_input", item.get("input", 0))
            rates = Rates(item["input"], cached, item["output"])
        records.append(
            {
                "name": _clean_model_name(str(item["name"])),
                "provider": str(item.get("provider") or provider),
                "source": source,
                "source_url": source_url,
                "api": _rates_payload(rates),
            }
        )
    return records


def _rates_from_portkey(item: dict[str, Any]) -> Rates | None:
    pricing_config = item.get("pricing_config")
    if not isinstance(pricing_config, dict):
        return None
    paygo = pricing_config.get("pay_as_you_go", {})
    if not isinstance(paygo, dict):
        return None
    input_rate = _portkey_price(paygo.get("request_token"))
    output_rate = _portkey_price(paygo.get("response_token"))
    if input_rate is None or output_rate is None:
        return None
    cached = _portkey_price(paygo.get("cache_read_input_token")) or input_rate
    cache_write = _portkey_price(paygo.get("cache_write_input_token"))
    additional = paygo.get("additional_units", {})
    cache_write_1h = None
    reasoning = None
    if isinstance(additional, dict):
        cache_write_1h = _portkey_price(additional.get("cache_write_1h"))
        reasoning = _portkey_price(additional.get("thinking_token"))
    return Rates(
        input_rate,
        cached,
        output_rate,
        reasoning_output=reasoning,
        cache_creation_input=cache_write,
        cache_creation_input_1h=cache_write_1h,
    )


def _rates_from_litellm(item: dict[str, Any]) -> Rates | None:
    input_rate = _litellm_price(item.get("input_cost_per_token"))
    output_rate = _litellm_price(item.get("output_cost_per_token"))
    if input_rate is None or output_rate is None:
        return None
    cached = (
        _litellm_price(item.get("cache_read_input_token_cost"))
        or _litellm_price(item.get("input_cost_per_token_cache_hit"))
        or input_rate
    )
    return Rates(
        input_rate,
        cached,
        output_rate,
        reasoning_output=_litellm_price(item.get("output_cost_per_reasoning_token")),
        cache_creation_input=_litellm_price(item.get("cache_creation_input_token_cost")),
        cache_creation_input_1h=_litellm_price(
            item.get("cache_creation_input_token_cost_above_1hr")
        ),
    )


def _long_context_from_litellm(item: dict[str, Any]) -> dict[str, Any] | None:
    input_rate = _litellm_price(item.get("input_cost_per_token"))
    output_rate = _litellm_price(item.get("output_cost_per_token"))
    if input_rate is None or output_rate is None:
        return None
    if input_rate <= 0 or output_rate <= 0:
        return None
    for threshold in (128_000, 200_000, 256_000, 272_000):
        suffix = f"{threshold // 1000}k_tokens"
        input_above = _litellm_price(item.get(f"input_cost_per_token_above_{suffix}"))
        output_above = _litellm_price(item.get(f"output_cost_per_token_above_{suffix}"))
        if input_above is None and output_above is None:
            continue
        return {
            "threshold": threshold,
            "input_mult": float((input_above or input_rate) / input_rate),
            "output_mult": float((output_above or output_rate) / output_rate),
        }
    return None


def _additional_units_from_portkey(item: dict[str, Any]) -> dict[str, str]:
    pricing_config = item.get("pricing_config")
    if not isinstance(pricing_config, dict):
        return {}
    paygo = pricing_config.get("pay_as_you_go", {})
    additional = paygo.get("additional_units") if isinstance(paygo, dict) else None
    if not isinstance(additional, dict):
        return {}
    values: dict[str, str] = {}
    for key, raw in additional.items():
        value = _portkey_price(raw)
        if value is not None:
            values[str(key)] = str(value)
    return values


def _merge_model_records(records: list[dict[str, Any]], prefer: str) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    prefer_source = "litellm" if prefer == "litellm" else "portkey"
    for record in records:
        keys = _model_keys(str(record.get("name") or ""))
        if not keys:
            continue
        key = keys[0]
        current = merged.get(key)
        if current is None:
            merged[key] = record | {"aliases": sorted(set(keys[1:]))}
            continue
        current_source = str(current.get("source") or "")
        incoming_source = str(record.get("source") or "")
        if incoming_source == prefer_source and current_source != prefer_source:
            base, overlay = record.copy(), current
        else:
            base, overlay = current, record
        merged[key] = _merge_record(base, overlay, keys)
    return sorted(
        merged.values(),
        key=lambda item: (str(item.get("provider") or ""), str(item["name"])),
    )


def _merge_record(
    base: dict[str, Any],
    overlay: dict[str, Any],
    overlay_keys: tuple[str, ...],
) -> dict[str, Any]:
    result = base.copy()
    for field_name in (
        "api",
        "long_context",
        "context_window",
        "max_output_tokens",
        "additional_units",
        "source_url",
    ):
        if not result.get(field_name) and overlay.get(field_name):
            result[field_name] = overlay[field_name]
    aliases = set(result.get("aliases") or ())
    aliases.update(overlay.get("aliases") or ())
    aliases.update(overlay_keys)
    result["aliases"] = sorted(alias for alias in aliases if alias != result.get("name"))
    return result


def _catalog_model_from_record(raw: dict[str, Any]) -> CatalogModel:
    additional_units = raw.get("additional_units", {})
    parsed_units = (
        {
            str(key): parsed
            for key, value in additional_units.items()
            if (parsed := _decimal_or_none(value)) is not None
        }
        if isinstance(additional_units, dict)
        else {}
    )
    return CatalogModel(
        name=_clean_model_name(str(raw["name"])),
        provider=str(raw.get("provider") or ""),
        api_rates=_rates_from_payload(raw.get("api")),
        long_context=_long_context_from_payload(raw.get("long_context")),
        context_window=_safe_int(raw.get("context_window")),
        max_output_tokens=_safe_int(raw.get("max_output_tokens")),
        source=str(raw.get("source") or ""),
        source_url=str(raw.get("source_url") or ""),
        aliases=tuple(str(item) for item in raw.get("aliases", []) if item),
        additional_units=parsed_units,
    )


def _rates_from_payload(raw: Any) -> Rates | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("input") in {"", None} or raw.get("output") in {"", None}:
        return None
    try:
        return Rates(
            raw["input"],
            raw.get("cached_input", raw["input"]),
            raw["output"],
            reasoning_output=raw.get("reasoning_output"),
            cache_creation_input=raw.get("cache_creation_input"),
            cache_creation_input_1h=raw.get("cache_creation_input_1h"),
        )
    except (InvalidOperation, ValueError):
        return None


def _long_context_from_payload(raw: Any) -> LongContextRule | None:
    if not isinstance(raw, dict) or not raw.get("threshold"):
        return None
    try:
        return LongContextRule(
            threshold=_safe_int(raw.get("threshold")),
            input_mult=float(raw.get("input_mult") or 1),
            output_mult=float(raw.get("output_mult") or 1),
        )
    except (TypeError, ValueError):
        return None


def _rates_payload(rates: Rates | None) -> dict[str, str] | None:
    if rates is None:
        return None
    return {
        "input": str(rates.input),
        "cached_input": str(rates.cached_input),
        "output": str(rates.output),
        "reasoning_output": (
            str(rates.reasoning_output) if rates.reasoning_output is not None else None
        ),
        "cache_creation_input": (
            str(rates.cache_creation_input) if rates.cache_creation_input is not None else None
        ),
        "cache_creation_input_1h": (
            str(rates.cache_creation_input_1h)
            if rates.cache_creation_input_1h is not None
            else None
        ),
    }


def _portkey_price(raw: Any) -> Decimal | None:
    if not isinstance(raw, dict) or raw.get("price") is None:
        return None
    value = _decimal_or_none(raw["price"])
    return value * Decimal("10000") if value is not None else None


def _litellm_price(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    value = _decimal_or_none(raw)
    return value * Decimal("1000000") if value is not None else None


def _decimal_or_none(raw: Any) -> Decimal | None:
    try:
        return decimal_value(raw)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _clean_model_name(value: str) -> str:
    raw = value.strip().lower().replace("_", "-")
    raw = raw.removeprefix("models/")
    if "/" in raw and not raw.startswith("openrouter/"):
        raw = raw.rsplit("/", 1)[-1]
    if raw.startswith("anthropic."):
        raw = raw.removeprefix("anthropic.")
    if raw.startswith("global.anthropic."):
        raw = raw.removeprefix("global.anthropic.")
    return raw


def _model_keys(*names: str) -> tuple[str, ...]:
    keys: list[str] = []
    for name in names:
        raw = _clean_model_name(name)
        if not raw:
            continue
        if raw.startswith("openrouter/"):
            candidates = [raw.split("/", 1)[1], raw]
        elif raw.startswith("bedrock/"):
            candidates = [raw.rsplit("/", 1)[-1], raw]
        else:
            candidates = [raw]
        for candidate in candidates:
            cleaned = _clean_model_name(candidate)
            canonical = _canonical_model_name(cleaned)
            for key in (canonical, cleaned):
                if key and key not in keys:
                    keys.append(key)
    return tuple(keys)


def _canonical_model_name(raw: str) -> str:
    replacements = {
        "gpt-5-5": "gpt-5.5",
        "gpt-5-4": "gpt-5.4",
        "gpt-5-3": "gpt-5.3",
        "gpt-5-2": "gpt-5.2",
        "gpt-5-1": "gpt-5.1",
        "claude-haiku-4-5": "claude-haiku-4.5",
        "claude-sonnet-4-6": "claude-sonnet-4.6",
        "claude-sonnet-4-5": "claude-sonnet-4.5",
        "claude-opus-4-7": "claude-opus-4.7",
        "claude-opus-4-6": "claude-opus-4.6",
        "claude-opus-4-5": "claude-opus-4.5",
        "claude-opus-4-1": "claude-opus-4.1",
    }
    for prefix, canonical in replacements.items():
        if raw == prefix or raw.startswith(f"{prefix}-"):
            return canonical if raw == prefix else canonical + raw.removeprefix(prefix)
    return raw


def _normal_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u2011", "-").replace("\u2010", "-").replace("\u2013", "-")
    text = text.replace("\u2014", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_datetime(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _validate_pricing_source(value: str) -> str:
    source = str(value or "auto").strip().lower()
    if source not in ALLOWED_PRICING_SOURCES:
        choices = ", ".join(sorted(ALLOWED_PRICING_SOURCES))
        raise ValueError(f"pricing source must be one of: {choices}")
    return source


def _empty_payload(source: str) -> dict[str, Any]:
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "source": source,
        "fetched_at": iso_z(dt.datetime.now(tz=dt.UTC)),
        "sources": [],
        "model_count": 0,
        "models": [],
    }
