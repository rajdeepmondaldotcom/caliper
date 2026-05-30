from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache

# Canonical labels for the entity that makes a model. Distinct from
# the tool vendor that wrote the log.
VENDOR_ANTHROPIC = "anthropic"
VENDOR_OPENAI = "openai"
VENDOR_GOOGLE = "google"
VENDOR_MISTRAL = "mistral"
VENDOR_META = "meta"
VENDOR_UNKNOWN = "unknown"

KNOWN_MODEL_VENDORS: tuple[str, ...] = (
    VENDOR_ANTHROPIC,
    VENDOR_OPENAI,
    VENDOR_GOOGLE,
    VENDOR_MISTRAL,
    VENDOR_META,
    VENDOR_UNKNOWN,
)

_MODEL_VENDOR_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude-", VENDOR_ANTHROPIC),
    ("claude/", VENDOR_ANTHROPIC),
    ("anthropic/", VENDOR_ANTHROPIC),
    ("gpt-", VENDOR_OPENAI),
    ("o1-", VENDOR_OPENAI),
    ("o3-", VENDOR_OPENAI),
    ("o4-", VENDOR_OPENAI),
    ("o5-", VENDOR_OPENAI),
    ("openai/", VENDOR_OPENAI),
    ("text-", VENDOR_OPENAI),
    ("gemini-", VENDOR_GOOGLE),
    ("google/", VENDOR_GOOGLE),
    ("palm-", VENDOR_GOOGLE),
    ("mistral-", VENDOR_MISTRAL),
    ("mistral/", VENDOR_MISTRAL),
    ("codestral", VENDOR_MISTRAL),
    ("llama-", VENDOR_META),
    ("meta/", VENDOR_META),
)


@lru_cache(maxsize=4096)
def model_vendor(model: str | None) -> str:
    """Return the canonical vendor label for a model id.

    Pure and called once per event per aggregation pass (millions of times on
    large logs), so the result is memoised on the model id. Sibling
    ``normalize_model`` is cached the same way.
    """
    if not model:
        return VENDOR_UNKNOWN
    lowered = str(model).strip().lower()
    if not lowered:
        return VENDOR_UNKNOWN
    for prefix, vendor in _MODEL_VENDOR_PREFIXES:
        if lowered.startswith(prefix):
            return vendor
    return VENDOR_UNKNOWN


def model_vendor_glyph(vendor: str) -> str:
    """Short single-character glyph for dense model-vendor displays."""
    return {
        VENDOR_ANTHROPIC: "A",
        VENDOR_OPENAI: "O",
        VENDOR_GOOGLE: "G",
        VENDOR_MISTRAL: "M",
        VENDOR_META: "L",
    }.get(vendor, "?")


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
