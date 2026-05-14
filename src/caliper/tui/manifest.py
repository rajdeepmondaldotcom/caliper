"""In-process TUI load manifests used to avoid rereading unchanged files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from caliper.models import RuntimeOptions
from caliper.vendors import enabled_vendors


@dataclass(frozen=True)
class FileIdentity:
    kind: str
    vendor: str
    path: str
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class TuiLoadManifest:
    options_key: tuple
    files: tuple[FileIdentity, ...]


def build_load_manifest(options: RuntimeOptions) -> TuiLoadManifest:
    """Return stable identities for parser inputs and parse-affecting files."""
    identities: list[FileIdentity] = []
    for vendor in enabled_vendors(options):
        try:
            paths = vendor.discover(options)
        except OSError:
            paths = []
        for path in paths:
            identity = _file_identity(path, kind="session", vendor=vendor.id)
            if identity is not None:
                identities.append(identity)
    for path in (
        options.state_db,
        options.config_path,
        options.tier_overrides,
        options.rates_file,
    ):
        if path is None:
            continue
        identity = _file_identity(path, kind="support", vendor="")
        if identity is not None:
            identities.append(identity)
    return TuiLoadManifest(
        options_key=_options_key(options),
        files=tuple(sorted(identities, key=lambda item: (item.kind, item.vendor, item.path))),
    )


def _file_identity(path: Path, *, kind: str, vendor: str) -> FileIdentity | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return FileIdentity(
        kind=kind,
        vendor=vendor,
        path=os.fspath(path),
        mtime_ns=stat.st_mtime_ns,
        size=stat.st_size,
    )


def _options_key(options: RuntimeOptions) -> tuple:
    return (
        os.fspath(options.session_root),
        os.fspath(options.state_db),
        os.fspath(options.config_path),
        options.start,
        options.end,
        options.timezone,
        options.pricing_mode,
        options.pricing_source,
        options.pricing_cache_ttl_hours,
        options.service_tier,
        options.unknown_service_tier,
        os.fspath(options.tier_overrides) if options.tier_overrides else "",
        os.fspath(options.rates_file) if options.rates_file else "",
        options.dedupe,
        options.parse_cache,
        options.default_model,
        options.show_prompts,
        options.offline,
        options.rate_limit_sample_limit,
        options.include_all_rate_limit_samples,
        options.order,
        options.start_of_week,
        options.project or "",
        options.cost_mode,
        options.vendors,
    )
