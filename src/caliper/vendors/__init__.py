from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from caliper.models import LoadResult, RuntimeOptions
from caliper.progress import NULL_PROGRESS, ParseProgress


class VendorParser(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def label(self) -> str: ...

    @property
    def schema_version(self) -> str: ...

    def discover(self, options: RuntimeOptions) -> Iterable[Path]: ...

    def parse(
        self,
        options: RuntimeOptions,
        progress: ParseProgress = NULL_PROGRESS,
    ) -> LoadResult: ...


VENDORS: dict[str, VendorParser] = {}


@dataclass(frozen=True)
class VendorSummary:
    id: str
    label: str
    schema_version: str
    files: int
    enabled: bool


def register_vendor(parser: VendorParser) -> VendorParser:
    VENDORS[parser.id] = parser
    return parser


def enabled_vendors(options: RuntimeOptions) -> list[VendorParser]:
    selected = _selected_vendor_ids(options.vendors)
    unknown = sorted(selected - {"all"} - set(VENDORS))
    if unknown:
        choices = ", ".join(["all", *sorted(VENDORS)])
        raise ValueError(f"--vendor must be one of: {choices}")
    ids = sorted(VENDORS) if "all" in selected else sorted(selected)
    return [VENDORS[vendor_id] for vendor_id in ids]


def vendor_file_count(options: RuntimeOptions) -> int:
    """Return the total number of files the enabled vendors would parse.

    Tolerates ``OSError`` from individual vendors so a single missing
    home directory does not abort the count. Used by the doctor command
    and by the Textual TUI loading overlay.
    """
    total = 0
    for vendor in enabled_vendors(options):
        try:
            total += sum(1 for _ in vendor.discover(options))
        except OSError:
            continue
    return total


def vendor_summaries(options: RuntimeOptions) -> list[VendorSummary]:
    selected = _selected_vendor_ids(options.vendors)
    active = set(VENDORS) if "all" in selected else selected
    rows: list[VendorSummary] = []
    for vendor_id, parser in sorted(VENDORS.items()):
        try:
            files = len(list(parser.discover(options)))
        except OSError:
            files = 0
        rows.append(
            VendorSummary(
                id=vendor_id,
                label=parser.label,
                schema_version=parser.schema_version,
                files=files,
                enabled=vendor_id in active,
            )
        )
    return rows


def _selected_vendor_ids(values: tuple[str, ...]) -> set[str]:
    selected = {value.strip() for value in values if value.strip()}
    return selected or {"all"}


from caliper.vendors import aider as _aider  # noqa: E402
from caliper.vendors import claude_code as _claude_code  # noqa: E402
from caliper.vendors import codex as _codex  # noqa: E402
from caliper.vendors import cursor as _cursor  # noqa: E402

register_vendor(_aider.PARSER)
register_vendor(_claude_code.PARSER)
register_vendor(_codex.PARSER)
register_vendor(_cursor.PARSER)
