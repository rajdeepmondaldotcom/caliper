from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Iterable
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
from caliper.parse_parallel import assert_accounted_paths, path_size, run_path_batches
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
        paths: Iterable[Path] | None = None,
    ) -> LoadResult:
        start = options.start.astimezone(dt.UTC)
        end = options.end.astimezone(dt.UTC)
        cache = ParseCache.default() if options.parse_cache else None
        events = []
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
            parsed_paths = _parse_uncached_paths(
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
            assert_accounted_paths(paths, accounted_paths, label="Cursor loader")
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


def _parse_uncached_paths(
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
                    vendor=VENDOR_CURSOR,
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
        _parse_cursor_batch,
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
                vendor=VENDOR_CURSOR,
                unsupported=unsupported,
            )
        parsed.append((path, _events_in_window(events, start=start, end=end), unsupported))
    assert_accounted_paths(
        paths,
        (path for path, _events, _unsupported in parsed),
        label="Cursor parser",
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


def _parse_cursor_batch(paths: tuple[Path, ...]) -> list[tuple[Path, list[UsageEvent], bool]]:
    out: list[tuple[Path, list[UsageEvent], bool]] = []
    for path in paths:
        events = _parse_path(path, progress=NULL_PROGRESS)
        out.append((path, events, not events))
    return out


def _parse_path(path: Path, progress: ParseProgress = NULL_PROGRESS) -> list[UsageEvent]:
    if path.name == "state.vscdb":
        return parse_vscdb(path)
    if "projects" in path.parts:
        return parse_project_jsonl(path, progress=progress)
    return parse_chat_jsonl(path, progress=progress)


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
