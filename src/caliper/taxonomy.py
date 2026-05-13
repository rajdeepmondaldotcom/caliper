from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelTaxonomyEntry:
    vendor: str
    raw_prefix: str
    canonical: str
    family: str
    generation: str
    variant: str
    tier: str


MODEL_TAXONOMY: tuple[ModelTaxonomyEntry, ...] = (
    ModelTaxonomyEntry("openai-codex", "gpt-5.5", "gpt-5.5", "gpt", "5.5", "", "frontier"),
    ModelTaxonomyEntry("openai-codex", "gpt-5.4", "gpt-5.4", "gpt", "5.4", "", "frontier"),
    ModelTaxonomyEntry(
        "openai-codex", "gpt-5.4-mini", "gpt-5.4-mini", "gpt", "5.4", "mini", "small"
    ),
    ModelTaxonomyEntry(
        "openai-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.3-codex-spark",
        "gpt",
        "5.3",
        "codex-spark",
        "small",
    ),
    ModelTaxonomyEntry(
        "openai-codex", "gpt-5.3-codex", "gpt-5.3-codex", "gpt", "5.3", "codex", "coding"
    ),
    ModelTaxonomyEntry(
        "claude-code",
        "claude-haiku-4",
        "claude-haiku-4.5",
        "claude",
        "4.5",
        "haiku",
        "small",
    ),
    ModelTaxonomyEntry(
        "claude-code",
        "claude-sonnet-4",
        "claude-sonnet-4.6",
        "claude",
        "4.6",
        "sonnet",
        "balanced",
    ),
    ModelTaxonomyEntry(
        "claude-code",
        "claude-opus-4",
        "claude-opus-4.7",
        "claude",
        "4.7",
        "opus",
        "premium",
    ),
)


def taxonomy_records() -> list[dict[str, str]]:
    return [asdict(entry) for entry in MODEL_TAXONOMY]


def lookup_model(vendor: str, model: str) -> ModelTaxonomyEntry | None:
    normalized = model.lower().replace("_", "-")
    for entry in MODEL_TAXONOMY:
        if entry.vendor == vendor and normalized.startswith(entry.raw_prefix):
            return entry
    return None
