from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from caliper.dedupe import dedupe_usage_events
from caliper.models import VENDOR_CURSOR, ThreadMeta, Usage, UsageEvent
from caliper.normalize import normalize_model
from caliper.timeutil import parse_event_timestamp


@dataclass(frozen=True)
class VscdbParseResult:
    events: list[UsageEvent]
    malformed_rows: int = 0


class _MalformedCursorRow(ValueError):
    pass


def parse_vscdb(path: Path) -> list[UsageEvent]:
    return parse_vscdb_detailed(path).events


def parse_vscdb_detailed(path: Path) -> VscdbParseResult:
    if not path.exists():
        return VscdbParseResult([])
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            rows = _cursor_usage_rows(conn) if _has_table(conn, "cursor_usage") else []
            if rows:
                events: list[UsageEvent] = []
                malformed_rows = 0
                for row in rows:
                    try:
                        events.append(_event_from_row(row, path))
                    except _MalformedCursorRow:
                        malformed_rows += 1
                return VscdbParseResult(events, malformed_rows)
            return VscdbParseResult(_events_from_kv_tables(conn, path))
    except sqlite3.Error:
        return VscdbParseResult([])


def _cursor_usage_rows(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        select timestamp, session_id, cwd, model, input_tokens, cached_input_tokens,
               output_tokens, total_tokens
        from cursor_usage
        """
    ).fetchall()


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "select 1 from sqlite_master where type = 'table' and name = ?",
            (name,),
        ).fetchone()
        is not None
    )


def _event_from_row(row, path: Path) -> UsageEvent:
    timestamp = parse_event_timestamp(str(row[0])) or dt.datetime.fromtimestamp(
        path.stat().st_mtime, tz=dt.UTC
    )
    raw_model = str(row[3] or "cursor-auto")
    model = normalize_model(VENDOR_CURSOR, raw_model)
    return UsageEvent(
        timestamp=timestamp,
        path=path,
        session_id=str(row[1] or path.stem),
        usage=Usage(
            input_tokens=_strict_int(row[4]),
            cached_input_tokens=_strict_int(row[5]),
            output_tokens=_strict_int(row[6]),
            total_tokens=_strict_int(row[7]),
        ),
        model=model,
        service_tier="standard",
        tier_source="vendor-default",
        thread=ThreadMeta(cwd=str(row[2] or ""), model=model, source=VENDOR_CURSOR),
        model_source="cursor-vscdb",
        usage_source="cursor_usage",
        vendor=VENDOR_CURSOR,
        dedupe_key=f"{path}:{timestamp.isoformat()}:{row[1]}:{row[7]}",
        raw_model=raw_model,
    )


def _strict_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError) as exc:
        raise _MalformedCursorRow from exc


def _events_from_kv_tables(conn: sqlite3.Connection, path: Path) -> list[UsageEvent]:
    events: list[UsageEvent] = []
    for table in ("ItemTable", "cursorDiskKV"):
        if not _has_table(conn, table):
            continue
        rows = conn.execute(
            f"""
            select key, value from {table}
            where lower(key) like '%usage%'
               or lower(key) like '%token%'
               or lower(key) like '%cost%'
            """,  # nosec B608
        ).fetchall()
        for key, value in rows:
            payload = _json_value(value)
            if payload is None:
                continue
            events.extend(_events_from_payload(payload, path, str(key or "")))
    return _dedupe_events(events)


def _json_value(value: object) -> Any | None:
    try:
        text = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        return json.loads(text)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _events_from_payload(payload: Any, path: Path, source_key: str) -> list[UsageEvent]:
    events: list[UsageEvent] = []
    for raw in _usage_objects(payload):
        event = _event_from_usage_object(raw, path, source_key)
        if event is not None:
            events.append(event)
    return events


def _usage_objects(value: Any):
    if isinstance(value, dict):
        if _has_usage_shape(value):
            yield value
        for key, child in value.items():
            if _is_prompt_like_key(str(key)):
                continue
            yield from _usage_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _usage_objects(child)


def _is_prompt_like_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in {"content", "message", "text", "prompt", "messages"}


def _has_usage_shape(raw: dict[str, Any]) -> bool:
    usage = raw.get("usage")
    if isinstance(usage, dict) and _usage_from_raw(usage).is_zero() is False:
        return _timestamp_from_raw(raw) is not None
    if _usage_from_raw(raw).is_zero():
        return False
    return _timestamp_from_raw(raw) is not None


def _event_from_usage_object(raw: dict[str, Any], path: Path, source_key: str) -> UsageEvent | None:
    timestamp = _timestamp_from_raw(raw)
    if timestamp is None:
        return None
    usage_raw = raw.get("usage") if isinstance(raw.get("usage"), dict) else raw
    usage = _usage_from_raw(usage_raw)
    if usage.is_zero():
        return None
    raw_model = str(
        raw.get("model") or raw.get("modelName") or raw.get("model_name") or "cursor-auto"
    )
    model = normalize_model(VENDOR_CURSOR, raw_model)
    session_id = str(
        raw.get("sessionId")
        or raw.get("session_id")
        or raw.get("composerId")
        or raw.get("conversationId")
        or source_key
        or path.stem
    )
    cwd = str(raw.get("cwd") or raw.get("workspacePath") or "")
    return UsageEvent(
        timestamp=timestamp,
        path=path,
        session_id=session_id,
        usage=usage,
        model=model,
        service_tier="standard",
        tier_source="vendor-default",
        thread=ThreadMeta(cwd=cwd, model=model, source=VENDOR_CURSOR),
        model_source="cursor-vscdb",
        usage_source="cursor-kv-json",
        vendor=VENDOR_CURSOR,
        event_id=str(raw.get("id") or raw.get("uuid") or ""),
        request_id=str(raw.get("requestId") or ""),
        dedupe_key=str(
            raw.get("id")
            or raw.get("uuid")
            or raw.get("requestId")
            or f"{path}:{source_key}:{timestamp.isoformat()}:{usage.total_tokens}"
        ),
        raw_model=raw_model,
    )


def _usage_from_raw(raw: Any) -> Usage:
    if not isinstance(raw, dict):
        return Usage()
    return Usage(
        input_tokens=_safe_int(
            raw.get("input_tokens")
            or raw.get("inputTokens")
            or raw.get("prompt_tokens")
            or raw.get("promptTokens")
        ),
        cached_input_tokens=_safe_int(
            raw.get("cached_input_tokens") or raw.get("cachedInputTokens")
        ),
        output_tokens=_safe_int(
            raw.get("output_tokens")
            or raw.get("outputTokens")
            or raw.get("completion_tokens")
            or raw.get("completionTokens")
        ),
        total_tokens=_safe_int(raw.get("total_tokens") or raw.get("totalTokens")),
    )


def _timestamp_from_raw(raw: dict[str, Any]) -> dt.datetime | None:
    for key in ("timestamp", "createdAt", "created_at", "time", "updatedAt", "lastUpdatedAt"):
        value = raw.get(key)
        timestamp = _parse_cursor_timestamp(value)
        if timestamp is not None:
            return timestamp
    return None


def _parse_cursor_timestamp(value: Any) -> dt.datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            return dt.datetime.fromtimestamp(seconds, tz=dt.UTC)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value)
    parsed = parse_event_timestamp(text)
    if parsed is not None:
        return parsed
    if text.isdigit():
        return _parse_cursor_timestamp(int(text))
    return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe_events(events: list[UsageEvent]) -> list[UsageEvent]:
    unique, _stats = dedupe_usage_events(events)
    return unique
