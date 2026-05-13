from __future__ import annotations

import datetime as dt
import json
import os
import re
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
from caliper.progress import NULL_PROGRESS, ParseProgress

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
    ) -> LoadResult:
        start = options.start.astimezone(dt.UTC)
        end = options.end.astimezone(dt.UTC)
        cache = ParseCache.default() if options.parse_cache else None
        events: list[UsageEvent] = []
        warnings: list[str] = []
        paths = self.discover(options)
        unsupported_paths: list[Path] = []
        files_with_events = 0
        try:
            paths_to_parse = paths
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
            for path in paths_to_parse:
                parsed, _has_supported_usage, unsupported = _parse_cached_history(
                    path,
                    cache,
                    start=start,
                    end=end,
                )
                if unsupported:
                    unsupported_paths.append(path)
                files_with_events += int(bool(parsed))
                events.extend(parsed)
                progress.file_done(path)
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
            credit_samples=[],
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


def _parse_cached_history(
    path: Path,
    cache: ParseCache | None,
    *,
    start: dt.datetime,
    end: dt.datetime,
) -> tuple[list[UsageEvent], bool, bool]:
    if cache is None:
        events = _parse_history(path)
        return _events_in_window(events, start=start, end=end), bool(events), not events
    indexed = cache.get_indexed_events(path, PARSER_CACHE_SIGNATURE, start=start, end=end)
    if indexed is not None:
        counts = cache.indexed_file_counts(path, PARSER_CACHE_SIGNATURE)
        has_supported_usage = bool(counts and counts[0] > 0)
        unsupported = bool(counts and counts[2])
        return indexed, has_supported_usage, unsupported
    cached = cache.get_events(path, PARSER_CACHE_SIGNATURE)
    if cached is not None:  # legacy blob cache migration path
        cache.put_indexed_events(
            path,
            PARSER_CACHE_SIGNATURE,
            cached,
            vendor=VENDOR_AIDER,
            unsupported=not cached,
        )
        return _events_in_window(cached, start=start, end=end), bool(cached), not cached
    events = _parse_history(path)
    cache.put_indexed_events(
        path,
        PARSER_CACHE_SIGNATURE,
        events,
        vendor=VENDOR_AIDER,
        unsupported=not events,
    )
    return _events_in_window(events, start=start, end=end), bool(events), not events


def _events_in_window(
    events: list[UsageEvent],
    *,
    start: dt.datetime,
    end: dt.datetime,
) -> list[UsageEvent]:
    return [event for event in events if start <= event.timestamp < end]


def _parse_history(path: Path) -> list[UsageEvent]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
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
                vendor_reported_api_dollars=Decimal(message_cost),
                source_line=index,
                event_id=f"{path}:{index}",
                dedupe_key=f"{path}:{index}:{message_cost}",
                raw_model="aider-reported",
            )
        )
    return events


PARSER = AiderParser()
