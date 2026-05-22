from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from caliper.models import LoadResult, RuntimeOptions
from caliper.progress import NULL_PROGRESS, ParseProgress


class VendorParser(Protocol):
    @property
    def id(self) -> str:
        raise NotImplementedError

    @property
    def label(self) -> str:
        raise NotImplementedError

    @property
    def schema_version(self) -> str:
        raise NotImplementedError

    def discover(self, options: RuntimeOptions) -> Iterable[Path]:
        raise NotImplementedError

    def parse(
        self,
        options: RuntimeOptions,
        progress: ParseProgress = NULL_PROGRESS,
        paths: Iterable[Path] | None = None,
    ) -> LoadResult:
        raise NotImplementedError


VENDORS: dict[str, VendorParser] = {}


@dataclass(frozen=True)
class VendorSummary:
    id: str
    label: str
    schema_version: str
    files: int
    enabled: bool


@dataclass(frozen=True)
class VendorDiscovery:
    id: str
    label: str
    schema_version: str
    paths: tuple[Path, ...]
    total_bytes: int = 0
    unreadable_files: int = 0

    @property
    def files(self) -> int:
        return len(self.paths)


@dataclass(frozen=True)
class UsageDiscovery:
    vendors: tuple[VendorDiscovery, ...]

    @property
    def total_files(self) -> int:
        return sum(item.files for item in self.vendors)

    @property
    def total_bytes(self) -> int:
        return sum(item.total_bytes for item in self.vendors)

    @property
    def unreadable_files(self) -> int:
        return sum(item.unreadable_files for item in self.vendors)

    def paths_for(self, vendor_id: str) -> list[Path]:
        for item in self.vendors:
            if item.id == vendor_id:
                return list(item.paths)
        return []

    def vendor_summary(self) -> str:
        active = [item for item in self.vendors if item.files]
        if not active:
            return "0 vendors"
        if len(active) <= 3:
            return ", ".join(f"{item.label} {item.files:,}" for item in active)
        first = ", ".join(f"{item.label} {item.files:,}" for item in active[:3])
        return f"{first}, +{len(active) - 3} more"


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


def discover_usage_files(
    options: RuntimeOptions,
    progress: ParseProgress = NULL_PROGRESS,
) -> UsageDiscovery:
    """Discover enabled vendor files once and compute the scan footprint."""
    vendors = enabled_vendors(options)
    progress.stage_start("discover", total=len(vendors))
    discovered: list[VendorDiscovery] = []
    for vendor in vendors:
        try:
            paths = tuple(sorted(set(vendor.discover(options))))
        except OSError:
            paths = ()
            unreadable = 1
            total_bytes = 0
        else:
            unreadable = 0
            total_bytes = 0
            for path in paths:
                try:
                    total_bytes += path.stat().st_size
                except OSError:
                    unreadable += 1
        discovered.append(
            VendorDiscovery(
                id=vendor.id,
                label=vendor.label,
                schema_version=vendor.schema_version,
                paths=paths,
                total_bytes=total_bytes,
                unreadable_files=unreadable,
            )
        )
        progress.stage_advance(detail=f"{vendor.label}: {len(paths):,} files")
    result = UsageDiscovery(tuple(discovered))
    progress.stage_done(
        "discover",
        summary=f"{result.total_files:,} files · {_format_discovery_bytes(result.total_bytes)}",
    )
    return result


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


def _format_discovery_bytes(size: int) -> str:
    value = float(max(size, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1000 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1000
    return f"{value:.1f} GB"


from caliper.vendors import aider as _aider  # noqa: E402
from caliper.vendors import claude_code as _claude_code  # noqa: E402
from caliper.vendors import codex as _codex  # noqa: E402
from caliper.vendors import cursor as _cursor  # noqa: E402

register_vendor(_aider.PARSER)
register_vendor(_claude_code.PARSER)
register_vendor(_codex.PARSER)
register_vendor(_cursor.PARSER)
