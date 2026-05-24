from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from caliper.models import (
    VENDOR_AIDER,
    LoadResult,
    ParserIssue,
    RuntimeOptions,
    ThreadMeta,
    Usage,
    UsageEvent,
    VendorParseStats,
)
from caliper.parse_cache import ParseCache
from caliper.parse_parallel import assert_accounted_paths, path_size, run_path_batches
from caliper.progress import NULL_PROGRESS, ParseProgress, report_file_progress

SUPPORTED_VERSIONS = ("inline-cost-v1",)
PARSER_CACHE_SIGNATURE = json.dumps(
    {"vendor": VENDOR_AIDER, "schema_version": "1", "parser": "aider-v3"},
    sort_keys=True,
)
TOKEN_COST_RE = re.compile(
    r"Tokens:\s*([0-9.]+)k sent,\s*([0-9.]+) received\.\s*"
    r"Cost:\s*\$([0-9.]+) message,\s*\$([0-9.]+) session\.",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AiderParser:
    id: str = VENDOR_AIDER
    label: str = "Aider"
    schema_version: str = "1"

    def discover(self, options: RuntimeOptions) -> list[Path]:
        del options
        root = Path(os.environ.get("CALIPER_AIDER_ROOT", ".")).expanduser()
        if not root.exists():
            return []
        return sorted(root.glob("**/.aider.chat.history.md"))

    def parse(
        self,
        options: RuntimeOptions,
        progress: ParseProgress = NULL_PROGRESS,
        paths: Iterable[Path] | None = None,
    ) -> LoadResult:
        start = options.start.astimezone(dt.UTC)
        end = options.end.astimezone(dt.UTC)
        cache = ParseCache.default() if options.parse_cache else None
        events: list[UsageEvent] = []
        warnings: list[str] = []
        paths = sorted(set(paths)) if paths is not None else sorted(set(self.discover(options)))
        unsupported_paths: list[Path] = []
        files_with_events = 0
        try:
            paths_to_parse = paths
            accounted_paths: list[Path] = []
            if cache is not None:
                cached = cache.get_indexed_events_for_paths(
                    paths,
                    PARSER_CACHE_SIGNATURE,
                    start=start,
                    end=end,
                )
                if cached is not None:
                    cached_events, _supported, cached_unsupported, paths_to_parse = cached
                    events.extend(cached_events)
                    files_with_events += len({event.path for event in cached_events})
                    unsupported_paths.extend(sorted(cached_unsupported))
                    for cached_path in set(paths) - set(paths_to_parse):
                        progress.cache_hit(cached_path)
                    accounted_paths.extend(set(paths) - set(paths_to_parse))
            parsed_paths = _parse_uncached_histories(
                paths_to_parse,
                options,
                start=start,
                end=end,
                progress=progress,
                cache=cache,
            )
            for path, parsed, unsupported in parsed_paths:
                if unsupported:
                    unsupported_paths.append(path)
                files_with_events += int(bool(parsed))
                events.extend(parsed)
                accounted_paths.append(path)
            assert_accounted_paths(paths, accounted_paths, label="Aider loader")
        finally:
            if cache is not None:
                cache.close()
        events.sort(key=lambda event: event.timestamp)
        issues = _unsupported_issues(unsupported_paths)
        return LoadResult(
            events=events,
            duplicates=0,
            tier_sources={"vendor-default": len(events)} if events else {},
            plan_types=set(),
            rate_limit_samples=[],
            warnings=warnings,
            parser_issues=issues,
            vendor_stats={
                VENDOR_AIDER: VendorParseStats(
                    vendor=VENDOR_AIDER,
                    discovered_files=len(paths),
                    files_with_events=files_with_events,
                    unsupported_files=len(unsupported_paths),
                    event_count=len(events),
                    warning_count=len(warnings) + len(issues),
                )
            },
        )


def _unsupported_issues(paths: list[Path]) -> list[ParserIssue]:
    if not paths:
        return []
    return [
        ParserIssue(
            vendor=VENDOR_AIDER,
            kind="unsupported:no_cost_line",
            message="Aider histories have no supported token/cost lines",
            count=len(paths),
            examples=tuple(str(path) for path in paths[:3]),
        )
    ]


def _parse_uncached_histories(
    paths: list[Path],
    options: RuntimeOptions,
    *,
    start: dt.datetime,
    end: dt.datetime,
    progress: ParseProgress,
    cache: ParseCache | None,
) -> list[tuple[Path, list[UsageEvent], bool]]:
    parsed: list[tuple[Path, list[UsageEvent], bool]] = []
    cold_paths: list[Path] = []
    if cache is not None:
        legacy_by_path = _legacy_events_for_paths(cache, paths)
        for path in paths:
            cached = legacy_by_path.get(path)
            if cached is not None:
                cache.put_indexed_events(
                    path,
                    PARSER_CACHE_SIGNATURE,
                    cached,
                    vendor=VENDOR_AIDER,
                    unsupported=not cached,
                )
                parsed.append((path, _events_in_window(cached, start=start, end=end), not cached))
                progress.cache_hit(path)
            else:
                cold_paths.append(path)
    else:
        cold_paths = list(paths)

    cold = run_path_batches(
        cold_paths,
        _parse_aider_batch,
        workers=options.parse_workers,
        size_of=path_size,
        on_batch_done=lambda batch, _result: _report_path_batch_done(batch, progress),
    )
    for path, events, unsupported in cold:
        if cache is not None:
            cache.put_indexed_events(
                path,
                PARSER_CACHE_SIGNATURE,
                events,
                vendor=VENDOR_AIDER,
                unsupported=unsupported,
            )
        parsed.append((path, _events_in_window(events, start=start, end=end), unsupported))
    assert_accounted_paths(
        paths,
        (path for path, _events, _unsupported in parsed),
        label="Aider parser",
    )
    return parsed


def _report_path_batch_done(batch: tuple[Path, ...], progress: ParseProgress) -> None:
    for path in batch:
        progress.file_done(path)


def _legacy_events_for_paths(
    cache: ParseCache,
    paths: list[Path],
) -> dict[Path, list[UsageEvent]]:
    get_events_for_paths = getattr(cache, "get_events_for_paths", None)
    if get_events_for_paths is not None:
        return get_events_for_paths(paths, PARSER_CACHE_SIGNATURE)
    out: dict[Path, list[UsageEvent]] = {}
    for path in paths:
        events = cache.get_events(path, PARSER_CACHE_SIGNATURE)
        if events is not None:
            out[path] = events
    return out


def _parse_aider_batch(paths: tuple[Path, ...]) -> list[tuple[Path, list[UsageEvent], bool]]:
    out: list[tuple[Path, list[UsageEvent], bool]] = []
    for path in paths:
        try:
            events = _parse_history(path, progress=NULL_PROGRESS)
        except OSError:
            events = []
        out.append((path, events, not events))
    return out


def _events_in_window(
    events: list[UsageEvent],
    *,
    start: dt.datetime,
    end: dt.datetime,
) -> list[UsageEvent]:
    return [event for event in events if start <= event.timestamp < end]


def _parse_history(path: Path, progress: ParseProgress = NULL_PROGRESS) -> list[UsageEvent]:
    try:
        total_bytes = path.stat().st_size
    except OSError:
        total_bytes = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if total_bytes:
        report_file_progress(progress, path, total_bytes, total_bytes)
    events: list[UsageEvent] = []
    timestamp = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
    for index, line in enumerate(lines, start=1):
        match = TOKEN_COST_RE.search(line)
        if not match:
            continue
        event_time = timestamp + dt.timedelta(microseconds=index)
        sent_k, received, message_cost, _session_cost = match.groups()
        input_tokens = int(Decimal(sent_k) * Decimal("1000"))
        output_tokens = int(Decimal(received))
        events.append(
            UsageEvent(
                timestamp=event_time,
                path=path,
                session_id=f"{path.parent.name or 'aider'}-{index}",
                usage=Usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                ),
                model="aider-reported",
                service_tier="standard",
                tier_source="vendor-default",
                thread=ThreadMeta(
                    cwd=str(path.parent),
                    model="aider-reported",
                    source=VENDOR_AIDER,
                ),
                model_source="aider-history",
                usage_source="aider-history",
                vendor=VENDOR_AIDER,
                vendor_reported_cost_usd=Decimal(message_cost),
                source_line=index,
                event_id=f"{path}:{index}",
                dedupe_key=f"{path}:{index}:{message_cost}",
                raw_model="aider-reported",
            )
        )
    return events


PARSER = AiderParser()
