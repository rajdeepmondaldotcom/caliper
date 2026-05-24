from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from caliper.dedupe import dedupe_usage_events
from caliper.models import (
    VENDOR_CLAUDE_CODE,
    LoadResult,
    RuntimeOptions,
    ThreadMeta,
    TurnFacts,
    Usage,
    UsageEvent,
    VendorParseStats,
)
from caliper.normalize import normalize_model, normalize_tier
from caliper.parse_cache import ParseCache
from caliper.parse_parallel import assert_accounted_paths, path_size, run_path_batches
from caliper.progress import NULL_PROGRESS, ParseProgress
from caliper.timeutil import parse_event_timestamp

SUPPORTED_SCHEMAS = ("1",)
PARSER_VERSION = "claude-code-v4"


@dataclass(frozen=True)
class ClaudeCodeParser:
    id: str = VENDOR_CLAUDE_CODE
    label: str = "Claude Code"
    schema_version: str = "1"

    def discover(self, options: RuntimeOptions) -> list[Path]:
        del options
        files: list[Path] = []
        for root in _claude_config_roots():
            projects = root / "projects"
            if not projects.exists():
                continue
            files.extend(_jsonl_files(projects))
        return sorted(set(files))

    def parse(
        self,
        options: RuntimeOptions,
        progress: ParseProgress = NULL_PROGRESS,
        paths: Iterable[Path] | None = None,
    ) -> LoadResult:
        start = options.start.astimezone(dt.UTC)
        end = options.end.astimezone(dt.UTC)
        events: list[UsageEvent] = []
        warnings: list[str] = []
        cache = ParseCache.default() if options.parse_cache else None
        paths = sorted(set(paths)) if paths is not None else sorted(set(self.discover(options)))
        files_with_events = 0
        try:
            paths_to_parse = paths
            accounted_paths: list[Path] = []
            if cache is not None:
                cached = cache.get_indexed_events_for_paths(
                    paths,
                    _parser_cache_signature(options),
                    start=start,
                    end=end,
                )
                if cached is not None:
                    cached_events, _supported_paths, _unsupported_paths, paths_to_parse = cached
                    events.extend(cached_events)
                    files_with_events += len({event.path for event in cached_events})
                    cached_paths = set(paths) - set(paths_to_parse)
                    for cached_path in cached_paths:
                        progress.cache_hit(cached_path)
                    accounted_paths.extend(cached_paths)
            parsed_paths = _parse_uncached_paths(
                paths_to_parse,
                options,
                start=start,
                end=end,
                progress=progress,
                cache=cache,
            )
            for path, parsed, warning in parsed_paths:
                if warning:
                    warnings.append(warning)
                    accounted_paths.append(path)
                    continue
                files_with_events += int(bool(parsed))
                events.extend(parsed)
                accounted_paths.append(path)
            assert_accounted_paths(paths, accounted_paths, label="Claude Code loader")
        finally:
            if cache is not None:
                cache.close()
        events, dedupe_stats = dedupe_usage_events(events)
        events.sort(key=lambda event: event.timestamp)
        return LoadResult(
            events=events,
            duplicates=dedupe_stats.duplicates,
            tier_sources={"vendor-default": len(events)} if events else {},
            plan_types=set(),
            rate_limit_samples=[],
            warnings=warnings,
            vendor_stats={
                VENDOR_CLAUDE_CODE: VendorParseStats(
                    vendor=VENDOR_CLAUDE_CODE,
                    discovered_files=len(paths),
                    files_with_events=files_with_events,
                    unsupported_files=0,
                    event_count=len(events),
                    warning_count=len(warnings),
                )
            },
            dedupe_stats=dedupe_stats.by_strategy,
        )


def _claude_config_roots() -> list[Path]:
    override = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if override:
        parts = [part.strip() for item in override.split(os.pathsep) for part in item.split(",")]
        return [Path(part).expanduser() for part in parts if part]
    roots = [Path.home() / ".claude"]
    xdg = os.environ.get("XDG_CONFIG_HOME")
    roots.append((Path(xdg).expanduser() if xdg else Path.home() / ".config") / "claude")
    return roots


def _jsonl_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.glob("**/*.jsonl")
        if "tool-results" not in path.parts and path.is_file()
    ]


def _parser_cache_signature(options: RuntimeOptions) -> str:
    return json.dumps(
        {
            "vendor": VENDOR_CLAUDE_CODE,
            "schema_version": "1",
            "parser": PARSER_VERSION,
            "cost_mode": options.cost_mode,
        },
        sort_keys=True,
    )


def _parse_uncached_paths(
    paths: list[Path],
    options: RuntimeOptions,
    *,
    start: dt.datetime,
    end: dt.datetime,
    progress: ParseProgress,
    cache: ParseCache | None,
) -> list[tuple[Path, list[UsageEvent], str]]:
    signature = _parser_cache_signature(options)
    parsed: list[tuple[Path, list[UsageEvent], str]] = []
    cold_paths: list[Path] = []
    if cache is not None:
        legacy_by_path = _legacy_events_for_paths(cache, paths, signature)
        for path in paths:
            legacy = legacy_by_path.get(path)
            if legacy is not None:
                cache.put_indexed_events(path, signature, legacy, vendor=VENDOR_CLAUDE_CODE)
                parsed.append((path, _events_in_window(legacy, start=start, end=end), ""))
                progress.cache_hit(path)
            else:
                cold_paths.append(path)
    else:
        cold_paths = list(paths)

    cold = run_path_batches(
        cold_paths,
        _parse_claude_batch,
        workers=options.parse_workers,
        size_of=path_size,
        worker_args=(options,),
        on_batch_done=lambda batch, _result: _report_path_batch_done(batch, progress),
    )
    for path, events, warning in cold:
        if cache is not None and not warning:
            cache.put_indexed_events(path, signature, events, vendor=VENDOR_CLAUDE_CODE)
        parsed.append((path, _events_in_window(events, start=start, end=end), warning))
    assert_accounted_paths(
        paths,
        (path for path, _events, _warning in parsed),
        label="Claude Code parser",
    )
    return parsed


def _report_path_batch_done(batch: tuple[Path, ...], progress: ParseProgress) -> None:
    for path in batch:
        progress.file_done(path)


def _legacy_events_for_paths(
    cache: ParseCache,
    paths: list[Path],
    signature: str,
) -> dict[Path, list[UsageEvent]]:
    get_events_for_paths = getattr(cache, "get_events_for_paths", None)
    if get_events_for_paths is not None:
        return get_events_for_paths(paths, signature)
    out: dict[Path, list[UsageEvent]] = {}
    for path in paths:
        events = cache.get_events(path, signature)
        if events is not None:
            out[path] = events
    return out


def _parse_claude_batch(
    paths: tuple[Path, ...],
    options: RuntimeOptions,
) -> list[tuple[Path, list[UsageEvent], str]]:
    out: list[tuple[Path, list[UsageEvent], str]] = []
    for path in paths:
        try:
            events = list(_parse_session(path, options, progress=NULL_PROGRESS))
        except OSError as exc:
            out.append((path, [], f"Claude Code session unreadable: {path}: {exc}"))
            continue
        out.append((path, events, ""))
    return out


def _events_in_window(
    events: list[UsageEvent],
    *,
    start: dt.datetime,
    end: dt.datetime,
) -> list[UsageEvent]:
    return [event for event in events if start <= event.timestamp < end]


def _parse_session(
    path: Path,
    options: RuntimeOptions,
    progress: ParseProgress = NULL_PROGRESS,
) -> list[UsageEvent]:
    events: list[UsageEvent] = []
    turn_counter: dict[str, int] = {}
    try:
        total_bytes = path.stat().st_size
    except OSError:
        total_bytes = 0
    bytes_read = 0
    next_report = 1_000_000
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            bytes_read += len(line)
            if total_bytes and bytes_read >= next_report:
                from caliper.progress import report_file_progress

                report_file_progress(progress, path, min(bytes_read, total_bytes), total_bytes)
                next_report = bytes_read + 1_000_000
            raw = _json_event_from_line(line)
            if raw is None:
                continue
            event = _usage_event(raw, path, line_number, options, turn_counter)
            if event is not None:
                events.append(event)
    if total_bytes:
        from caliper.progress import report_file_progress

        report_file_progress(progress, path, total_bytes, total_bytes)
    return events


def _json_event_from_line(line: str) -> dict[str, Any] | None:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None


def _usage_event(
    raw: dict[str, Any],
    path: Path,
    line_number: int,
    options: RuntimeOptions,
    turn_counter: dict[str, int],
) -> UsageEvent | None:
    message = raw.get("message")
    if not isinstance(message, dict):
        return None
    usage_raw = message.get("usage")
    if not isinstance(usage_raw, dict):
        return None
    timestamp = parse_event_timestamp(str(raw.get("timestamp") or ""))
    if timestamp is None:
        return None
    usage = _usage_from_claude(usage_raw)
    if usage.is_zero():
        return None
    raw_model = str(message.get("model") or raw.get("model") or "")
    model = normalize_model(VENDOR_CLAUDE_CODE, raw_model)
    service_tier = _service_tier_from_usage(usage_raw)
    message_id = str(message.get("id") or "")
    request_id = str(raw.get("requestId") or "")
    dedupe_key = f"{message_id}:{request_id}" if message_id and request_id else ""
    cwd = str(raw.get("cwd") or "")
    thread = ThreadMeta(
        rollout_path=str(path),
        cwd=cwd,
        git_branch=str(raw.get("gitBranch") or ""),
        model=model,
        cli_version=str(raw.get("version") or ""),
        source=VENDOR_CLAUDE_CODE,
        thread_source=VENDOR_CLAUDE_CODE,
    )
    vendor_cost = _vendor_cost(raw, options.cost_mode)
    session_id = str(raw.get("sessionId") or path.stem)
    turn_index = turn_counter.get(session_id, 0)
    turn_counter[session_id] = turn_index + 1
    turn_facts = _turn_facts_from_message(message, raw, turn_index)
    return UsageEvent(
        timestamp=timestamp,
        path=path,
        session_id=session_id,
        usage=usage,
        model=model,
        service_tier=service_tier,
        tier_source="vendor-default",
        thread=thread,
        model_source="message",
        usage_source="message.usage",
        vendor=VENDOR_CLAUDE_CODE,
        vendor_reported_cost_usd=vendor_cost,
        source_line=line_number,
        event_id=str(raw.get("uuid") or message_id or ""),
        message_id=message_id,
        request_id=request_id,
        dedupe_key=dedupe_key,
        raw_model=raw_model,
        turn_facts=turn_facts,
    )


def _turn_facts_from_message(
    message: dict[str, Any],
    raw: dict[str, Any],
    turn_index: int,
) -> TurnFacts:
    content = message.get("content")
    tool_names: list[str] = []
    skill_names: list[str] = []
    tool_use_count = 0
    has_thinking = False
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type == "tool_use":
                tool_use_count += 1
                name = block.get("name")
                if isinstance(name, str) and name:
                    tool_names.append(name)
                if name == "Skill":
                    skill_name = _skill_name_from_tool_use(block)
                    if skill_name:
                        skill_names.append(skill_name)
            elif block_type == "thinking":
                has_thinking = True
    return TurnFacts(
        turn_index=turn_index,
        parent_uuid=str(raw.get("parentUuid") or ""),
        tool_use_count=tool_use_count,
        tool_names=tuple(tool_names),
        skill_names=tuple(skill_names),
        has_thinking_block=has_thinking,
    )


def _skill_name_from_tool_use(block: dict[str, Any]) -> str:
    """Extract only the skill identifier from a Claude Code Skill tool call.

    The input payload can contain arguments or free-form text. Caliper keeps
    only the skill name and drops everything else.
    """
    raw_input = block.get("input")
    if not isinstance(raw_input, dict):
        return ""
    for key in ("skill", "name", "skill_name"):
        value = raw_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return ""


def _usage_from_claude(raw: dict[str, Any]) -> Usage:
    input_tokens = _safe_int(raw.get("input_tokens"))
    cache_creation = _safe_int(raw.get("cache_creation_input_tokens"))
    cache_read = _safe_int(raw.get("cache_read_input_tokens"))
    cache_creation_1h = _safe_int(raw.get("cache_creation_input_1h_tokens"))
    output_tokens = _safe_int(raw.get("output_tokens"))
    total_input = input_tokens + cache_creation + cache_read + cache_creation_1h
    total = _safe_int(raw.get("total_tokens")) or total_input + output_tokens
    return Usage(
        input_tokens=total_input,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
        cache_creation_input_1h_tokens=cache_creation_1h,
        output_tokens=output_tokens,
        total_tokens=total,
    )


def _service_tier_from_usage(raw: dict[str, Any]) -> str:
    return normalize_tier(str(raw.get("speed") or raw.get("service_tier") or "")) or "standard"


def _vendor_cost(raw: dict[str, Any], cost_mode: str) -> Decimal | None:
    if cost_mode == "calculate":
        return None
    value = raw.get("costUSD")
    if value is None:
        return Decimal("0") if cost_mode == "display" else None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0") if cost_mode == "display" else None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


PARSER = ClaudeCodeParser()
