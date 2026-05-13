from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

from caliper.models import (
    VENDOR_CURSOR,
    LoadResult,
    ParserIssue,
    RuntimeOptions,
    UsageEvent,
    VendorParseStats,
)
from caliper.parse_cache import ParseCache
from caliper.progress import NULL_PROGRESS, ParseProgress
from caliper.vendors.cursor.chats import parse_chat_jsonl
from caliper.vendors.cursor.projects import parse_project_jsonl
from caliper.vendors.cursor.vscdb import parse_vscdb

PARSER_CACHE_SIGNATURE = json.dumps(
    {"vendor": VENDOR_CURSOR, "schema_version": "1", "parser": "cursor-v4"},
    sort_keys=True,
)


@dataclass(frozen=True)
class CursorParser:
    id: str = VENDOR_CURSOR
    label: str = "Cursor"
    schema_version: str = "1"

    def discover(self, options: RuntimeOptions) -> list[Path]:
        del options
        root = _cursor_root()
        files: list[Path] = []
        files.extend((root / "User" / "globalStorage").glob("state.vscdb"))
        files.extend((root / "User" / "workspaceStorage").glob("*/state.vscdb"))
        files.extend((root / "projects").glob("**/*.jsonl"))
        files.extend((root / "chats").glob("**/*.jsonl"))
        files.extend((root / "acp-sessions").glob("**/*.jsonl"))
        if "CALIPER_CURSOR_HOME" not in os.environ:
            files.extend((Path.home() / ".cursor" / "projects").glob("**/*.jsonl"))
            files.extend((Path.home() / ".cursor" / "chats").glob("**/*.jsonl"))
            files.extend((Path.home() / ".cursor" / "acp-sessions").glob("**/*.jsonl"))
        return sorted(path for path in set(files) if path.exists())

    def parse(
        self,
        options: RuntimeOptions,
        progress: ParseProgress = NULL_PROGRESS,
    ) -> LoadResult:
        start = options.start.astimezone(dt.UTC)
        end = options.end.astimezone(dt.UTC)
        cache = ParseCache.default() if options.parse_cache else None
        events = []
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
                parsed, _has_supported_usage, unsupported = _parse_cached_path(
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
                VENDOR_CURSOR: VendorParseStats(
                    vendor=VENDOR_CURSOR,
                    discovered_files=len(paths),
                    files_with_events=files_with_events,
                    unsupported_files=len(unsupported_paths),
                    event_count=len(events),
                    warning_count=len(warnings) + len(issues),
                )
            },
        )


def _cursor_root() -> Path:
    override = os.environ.get("CALIPER_CURSOR_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(user_data_dir("Cursor"))


def _parse_cached_path(
    path: Path,
    cache: ParseCache | None,
    *,
    start: dt.datetime,
    end: dt.datetime,
) -> tuple[list[UsageEvent], bool, bool]:
    if cache is None:
        events = _parse_path(path)
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
            vendor=VENDOR_CURSOR,
            unsupported=not cached,
        )
        return _events_in_window(cached, start=start, end=end), bool(cached), not cached
    events = _parse_path(path)
    cache.put_indexed_events(
        path,
        PARSER_CACHE_SIGNATURE,
        events,
        vendor=VENDOR_CURSOR,
        unsupported=not events,
    )
    return _events_in_window(events, start=start, end=end), bool(events), not events


def _parse_path(path: Path) -> list[UsageEvent]:
    if path.name == "state.vscdb":
        return parse_vscdb(path)
    if "projects" in path.parts:
        return parse_project_jsonl(path)
    return parse_chat_jsonl(path)


def _events_in_window(
    events: list[UsageEvent],
    *,
    start: dt.datetime,
    end: dt.datetime,
) -> list[UsageEvent]:
    return [event for event in events if start <= event.timestamp < end]


def _unsupported_issues(paths: list[Path]) -> list[ParserIssue]:
    if not paths:
        return []
    return [
        ParserIssue(
            vendor=VENDOR_CURSOR,
            kind="unsupported:no_token_usage",
            message="Cursor files have no per-event token counts",
            count=len(paths),
            examples=tuple(str(path) for path in paths[:3]),
        )
    ]


PARSER = CursorParser()
