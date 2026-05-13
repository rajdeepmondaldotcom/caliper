from __future__ import annotations

from caliper.pricing import normalize_model as normalize_priced_model
from caliper.pricing import normalize_service_tier
from caliper.taxonomy import lookup_model


def normalize_model(vendor: str, model: str | None) -> str:
    raw = (model or "").strip()
    entry = lookup_model(vendor, raw)
    if entry is not None:
        return entry.canonical
    return normalize_priced_model(raw)


def normalize_tier(value: str | None) -> str:
    return normalize_service_tier(value)
