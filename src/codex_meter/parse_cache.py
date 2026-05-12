from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from codex_meter.models import (
    ParsedSessionRecord,
    RateLimitSample,
    ThreadMeta,
    Usage,
    UsageEvent,
)


def default_cache_path() -> Path:
    override = os.environ.get("CODEX_METER_CACHE_DIR")
    if override:
        return Path(override).expanduser() / "parse_cache.sqlite"
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "codex-meter" / "parse_cache.sqlite"
    return Path.home() / ".cache" / "codex-meter" / "parse_cache.sqlite"


@dataclass(frozen=True)
class CacheStats:
    path: Path
    hits: int = 0
    misses: int = 0


class ParseCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_cache_path()
        self.hits = 0
        self.misses = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                """
                create table if not exists parsed_sessions (
                    path text not null,
                    signature text not null,
                    mtime_ns integer not null,
                    size integer not null,
                    byte_offset integer not null,
                    payload blob not null,
                    primary key (path, signature)
                )
                """
            )

    @classmethod
    def default(cls) -> ParseCache:
        return cls(default_cache_path())

    def get(self, path: Path, signature: str):
        stat = path.stat()
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                """
                select payload from parsed_sessions
                where path = ? and signature = ? and mtime_ns = ? and size = ? and byte_offset = ?
                """,
                (str(path), signature, stat.st_mtime_ns, stat.st_size, stat.st_size),
            ).fetchone()
        if row is None:
            self.misses += 1
            return None
        parsed = _decode_payload(row[0])
        if parsed is None:
            self.misses += 1
            return None
        self.hits += 1
        return parsed

    def put(self, path: Path, signature: str, parsed) -> None:
        stat = path.stat()
        payload = _encode_payload(parsed)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                """
                insert or replace into parsed_sessions
                    (path, signature, mtime_ns, size, byte_offset, payload)
                values (?, ?, ?, ?, ?, ?)
                """,
                (str(path), signature, stat.st_mtime_ns, stat.st_size, stat.st_size, payload),
            )

    def stats(self) -> CacheStats:
        return CacheStats(path=self.path, hits=self.hits, misses=self.misses)


def _encode_datetime(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat()


def _decode_datetime(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value).astimezone(dt.UTC)


def _usage_to_dict(usage: Usage) -> dict:
    return asdict(usage)


def _usage_from_dict(raw: dict) -> Usage:
    return Usage.from_dict(raw)


def _thread_to_dict(thread: ThreadMeta) -> dict:
    return asdict(thread)


def _thread_from_dict(raw: dict) -> ThreadMeta:
    names = {field.name for field in fields(ThreadMeta)}
    return ThreadMeta(**{key: value for key, value in raw.items() if key in names})


def _event_to_dict(event: UsageEvent) -> dict:
    item = asdict(event)
    item["timestamp"] = _encode_datetime(event.timestamp)
    item["path"] = str(event.path)
    item["usage"] = _usage_to_dict(event.usage)
    item["thread"] = _thread_to_dict(event.thread)
    return item


def _event_from_dict(raw: dict) -> UsageEvent:
    item = dict(raw)
    item["timestamp"] = _decode_datetime(str(item["timestamp"]))
    item["path"] = Path(str(item["path"]))
    item["usage"] = _usage_from_dict(item["usage"])
    item["thread"] = _thread_from_dict(item["thread"])
    names = {field.name for field in fields(UsageEvent)}
    return UsageEvent(**{key: value for key, value in item.items() if key in names})


def _sample_to_dict(sample: RateLimitSample) -> dict:
    item = asdict(sample)
    item["timestamp"] = _encode_datetime(sample.timestamp)
    item["path"] = str(sample.path)
    return item


def _sample_from_dict(raw: dict) -> RateLimitSample:
    item = dict(raw)
    item["timestamp"] = _decode_datetime(str(item["timestamp"]))
    item["path"] = Path(str(item["path"]))
    return RateLimitSample(**item)


def _encode_payload(parsed) -> bytes:
    records = []
    for item in parsed:
        record = _coerce_record(item)
        records.append(
            {
                "event": _event_to_dict(record.event) if record.event is not None else None,
                "reset": bool(record.counter_reset),
                "sample": _sample_to_dict(record.sample) if record.sample is not None else None,
            }
        )
    return json.dumps({"version": 1, "records": records}, separators=(",", ":")).encode("utf-8")


def _decode_payload(raw) -> list[ParsedSessionRecord] | None:
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = json.loads(text)
    except (AttributeError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return None
    records = payload.get("records")
    if not isinstance(records, list):
        return None
    parsed: list[ParsedSessionRecord] = []
    try:
        for record in records:
            if not isinstance(record, dict):
                return None
            event_raw = record.get("event")
            sample_raw = record.get("sample")
            parsed.append(
                ParsedSessionRecord(
                    event=_event_from_dict(event_raw) if isinstance(event_raw, dict) else None,
                    counter_reset=bool(record.get("reset")),
                    sample=_sample_from_dict(sample_raw) if isinstance(sample_raw, dict) else None,
                )
            )
    except (KeyError, TypeError, ValueError):
        return None
    return parsed


def _coerce_record(record) -> ParsedSessionRecord:
    if isinstance(record, ParsedSessionRecord):
        return record
    event, reset, sample = record
    return ParsedSessionRecord(event=event, counter_reset=bool(reset), sample=sample)
