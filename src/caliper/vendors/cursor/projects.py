from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from caliper.models import VENDOR_CURSOR, ThreadMeta, Usage, UsageEvent
from caliper.normalize import normalize_model
from caliper.progress import NULL_PROGRESS, ParseProgress, report_file_progress
from caliper.timeutil import parse_event_timestamp


def parse_project_jsonl(
    path: Path,
    progress: ParseProgress = NULL_PROGRESS,
) -> list[UsageEvent]:
    events: list[UsageEvent] = []
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return events
    try:
        total_bytes = path.stat().st_size
    except OSError:
        total_bytes = 0
    bytes_read = 0
    next_report = 1_000_000
    with handle:
        for line in handle:
            bytes_read += len(line)
            if total_bytes and bytes_read >= next_report:
                report_file_progress(progress, path, min(bytes_read, total_bytes), total_bytes)
                next_report = bytes_read + 1_000_000
            if not _line_has_usage_marker(line):
                continue
            raw = _json_obj(line)
            if raw is None:
                continue
            event = _event_from_json(raw, path)
            if event:
                events.append(event)
    if total_bytes:
        report_file_progress(progress, path, total_bytes, total_bytes)
    return events


def _line_has_usage_marker(line: str) -> bool:
    return any(
        marker in line
        for marker in (
            '"usage"',
            '"input_tokens"',
            '"inputTokens"',
            '"output_tokens"',
            '"outputTokens"',
            '"total_tokens"',
            '"totalTokens"',
        )
    )


def _json_obj(line: str) -> dict[str, Any] | None:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None


def _event_from_json(raw: dict[str, Any], path: Path) -> UsageEvent | None:
    usage_raw = raw.get("usage")
    if not isinstance(usage_raw, dict):
        return None
    timestamp = parse_event_timestamp(str(raw.get("timestamp") or ""))
    if timestamp is None:
        return None
    raw_model = str(raw.get("model") or "cursor-auto")
    model = normalize_model(VENDOR_CURSOR, raw_model)
    usage = Usage.from_dict(usage_raw)
    if usage.is_zero():
        return None
    return UsageEvent(
        timestamp=timestamp,
        path=path,
        session_id=str(raw.get("sessionId") or raw.get("session_id") or path.stem),
        usage=usage,
        model=model,
        service_tier="standard",
        tier_source="vendor-default",
        thread=ThreadMeta(cwd=str(raw.get("cwd") or ""), model=model, source=VENDOR_CURSOR),
        model_source="cursor-json",
        usage_source="cursor-json",
        vendor=VENDOR_CURSOR,
        event_id=str(raw.get("id") or raw.get("uuid") or ""),
        request_id=str(raw.get("requestId") or ""),
        dedupe_key=str(
            raw.get("id")
            or raw.get("uuid")
            or raw.get("requestId")
            or f"{path}:{timestamp.isoformat()}:{usage.total_tokens}"
        ),
        raw_model=raw_model,
    )
