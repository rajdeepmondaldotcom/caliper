from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import sqlite3
from dataclasses import asdict, dataclass, fields
from decimal import Decimal
from pathlib import Path

from caliper.models import (
    ParsedSessionRecord,
    RateLimitSample,
    ThreadMeta,
    TurnFacts,
    Usage,
    UsageEvent,
)

THREAD_META_FIELDS = {field.name for field in fields(ThreadMeta)}
USAGE_EVENT_FIELDS = {field.name for field in fields(UsageEvent)}


def default_cache_path() -> Path:
    override = os.environ.get("CALIPER_CACHE_DIR")
    if override:
        return Path(override).expanduser() / "parse_cache.sqlite"
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "caliper" / "parse_cache.sqlite"
    return Path.home() / ".cache" / "caliper" / "parse_cache.sqlite"


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
        self._conn = sqlite3.connect(self.path)
        # WAL lets concurrent readers run alongside one writer, so two Caliper
        # processes (e.g. `dashboard` + `live`) sharing the cache don't deadlock;
        # busy_timeout turns immediate "database is locked" errors into a short
        # wait. Both are safe per connection.
        with contextlib.suppress(sqlite3.DatabaseError):
            self._conn.execute("pragma journal_mode=WAL")
            self._conn.execute("pragma busy_timeout=10000")
            self._conn.execute("pragma synchronous=NORMAL")
        self._closed = False
        with self._conn:
            self._conn.execute(
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
            self._conn.execute(
                """
                create table if not exists parsed_vendor_events (
                    path text not null,
                    signature text not null,
                    mtime_ns integer not null,
                    size integer not null,
                    payload blob not null,
                    primary key (path, signature)
                )
                """
            )
            self._conn.execute(
                """
                create table if not exists indexed_parse_files (
                    path text not null,
                    signature text not null,
                    vendor text not null,
                    mtime_ns integer not null,
                    size integer not null,
                    event_count integer not null,
                    sample_count integer not null,
                    unsupported integer not null default 0,
                    min_timestamp text not null default '',
                    max_timestamp text not null default '',
                    updated_at text not null,
                    primary key (path, signature)
                )
                """
            )
            self._conn.execute(
                """
                create table if not exists indexed_parse_events (
                    path text not null,
                    signature text not null,
                    row_index integer not null,
                    timestamp text not null,
                    counter_reset integer not null default 0,
                    payload blob not null,
                    primary key (path, signature, row_index)
                )
                """
            )
            self._conn.execute(
                """
                create table if not exists indexed_parse_samples (
                    path text not null,
                    signature text not null,
                    row_index integer not null,
                    timestamp text not null,
                    payload blob not null,
                    primary key (path, signature, row_index)
                )
                """
            )
            self._conn.execute(
                """
                create index if not exists idx_indexed_parse_events_window
                on indexed_parse_events (path, signature, timestamp)
                """
            )
            self._conn.execute(
                """
                create index if not exists idx_indexed_parse_samples_window
                on indexed_parse_samples (path, signature, timestamp)
                """
            )

    @classmethod
    def default(cls) -> ParseCache:
        return cls(default_cache_path())

    def get(self, path: Path, signature: str):
        stat = path.stat()
        row = self._conn.execute(
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
        with self._conn:
            self._conn.execute(
                """
                insert or replace into parsed_sessions
                    (path, signature, mtime_ns, size, byte_offset, payload)
                values (?, ?, ?, ?, ?, ?)
                """,
                (str(path), signature, stat.st_mtime_ns, stat.st_size, stat.st_size, payload),
            )

    def get_events(self, path: Path, signature: str) -> list[UsageEvent] | None:
        stat = path.stat()
        row = self._conn.execute(
            """
            select payload from parsed_vendor_events
            where path = ? and signature = ? and mtime_ns = ? and size = ?
            """,
            (str(path), signature, stat.st_mtime_ns, stat.st_size),
        ).fetchone()
        if row is None:
            self.misses += 1
            return None
        events = _decode_events_payload(row[0])
        if events is None:
            self.misses += 1
            return None
        self.hits += 1
        return events

    def put_events(self, path: Path, signature: str, events: list[UsageEvent]) -> None:
        stat = path.stat()
        payload = _encode_events_payload(events)
        with self._conn:
            self._conn.execute(
                """
                insert or replace into parsed_vendor_events
                    (path, signature, mtime_ns, size, payload)
                values (?, ?, ?, ?, ?)
                """,
                (str(path), signature, stat.st_mtime_ns, stat.st_size, payload),
            )

    def get_records(
        self,
        path: Path,
        signature: str,
        *,
        start: dt.datetime,
        end: dt.datetime,
    ) -> list[ParsedSessionRecord] | None:
        if not self._indexed_file_is_fresh(path, signature):
            self.misses += 1
            return None
        start_key = _encode_datetime(start)
        end_key = _encode_datetime(end)
        records: list[ParsedSessionRecord] = []
        for row in self._conn.execute(
            """
            select counter_reset, payload from indexed_parse_events
            where path = ? and signature = ? and timestamp >= ? and timestamp < ?
            order by timestamp, row_index
            """,
            (str(path), signature, start_key, end_key),
        ):
            event = _event_from_index_payload(row[1])
            if event is None:
                self.misses += 1
                return None
            records.append(ParsedSessionRecord(event=event, counter_reset=bool(row[0])))
        for row in self._conn.execute(
            """
            select payload from indexed_parse_samples
            where path = ? and signature = ? and timestamp >= ? and timestamp < ?
            order by timestamp, row_index
            """,
            (str(path), signature, start_key, end_key),
        ):
            sample = _sample_from_index_payload(row[0])
            if sample is None:
                self.misses += 1
                return None
            records.append(ParsedSessionRecord(sample=sample))
        self.hits += 1
        return records

    def put_records(
        self,
        path: Path,
        signature: str,
        records,
        *,
        vendor: str,
        unsupported: bool = False,
    ) -> None:
        stat = path.stat()
        parsed = [_coerce_record(record) for record in records]
        event_rows = []
        sample_rows = []
        timestamps: list[str] = []
        for index, record in enumerate(parsed):
            if record.event is not None:
                timestamp = _encode_datetime(record.event.timestamp)
                timestamps.append(timestamp)
                event_rows.append(
                    (
                        str(path),
                        signature,
                        index,
                        timestamp,
                        int(record.counter_reset),
                        _encode_index_payload(_event_to_dict(record.event)),
                    )
                )
            if record.sample is not None:
                timestamp = _encode_datetime(record.sample.timestamp)
                timestamps.append(timestamp)
                sample_rows.append(
                    (
                        str(path),
                        signature,
                        index,
                        timestamp,
                        _encode_index_payload(_sample_to_dict(record.sample)),
                    )
                )
        self._replace_indexed_rows(
            path,
            signature,
            vendor=vendor,
            stat=stat,
            event_rows=event_rows,
            sample_rows=sample_rows,
            unsupported=unsupported,
            timestamps=timestamps,
        )

    def get_indexed_events(
        self,
        path: Path,
        signature: str,
        *,
        start: dt.datetime,
        end: dt.datetime,
    ) -> list[UsageEvent] | None:
        records = self.get_records(path, signature, start=start, end=end)
        if records is None:
            return None
        return [record.event for record in records if record.event is not None]

    def get_indexed_events_for_paths(
        self,
        paths: list[Path],
        signature: str,
        *,
        start: dt.datetime,
        end: dt.datetime,
    ) -> tuple[list[UsageEvent], set[Path], set[Path], list[Path]] | None:
        stat_by_path: dict[str, os.stat_result] = {}
        path_by_text: dict[str, Path] = {}
        for path in paths:
            try:
                stat_by_path[str(path)] = path.stat()
            except OSError:
                continue
            path_by_text[str(path)] = path
        if not stat_by_path:
            return [], set(), set(), paths

        fresh_paths: set[str] = set()
        supported_paths: set[Path] = set()
        unsupported_paths: set[Path] = set()
        for chunk in _chunks(list(stat_by_path), 500):
            placeholders = ",".join("?" for _ in chunk)
            rows = self._conn.execute(
                f"""
                select path, mtime_ns, size, event_count, unsupported
                from indexed_parse_files
                where signature = ? and path in ({placeholders})
                """,  # nosec B608
                (signature, *chunk),
            ).fetchall()
            for path_text, mtime_ns, size, event_count, unsupported in rows:
                stat = stat_by_path.get(str(path_text))
                if stat is None or stat.st_mtime_ns != mtime_ns or stat.st_size != size:
                    continue
                fresh_paths.add(str(path_text))
                path = path_by_text[str(path_text)]
                if int(event_count or 0) > 0:
                    supported_paths.add(path)
                if unsupported:
                    unsupported_paths.add(path)

        missing = [path for path in paths if str(path) not in fresh_paths]
        start_key = _encode_datetime(start)
        end_key = _encode_datetime(end)
        events: list[UsageEvent] = []
        event_paths = [str(path) for path in supported_paths]
        for chunk in _chunks(event_paths, 500):
            placeholders = ",".join("?" for _ in chunk)
            rows = self._conn.execute(
                f"""
                select payload from indexed_parse_events
                where signature = ? and path in ({placeholders})
                  and timestamp >= ? and timestamp < ?
                order by timestamp, path, row_index
                """,  # nosec B608
                (signature, *chunk, start_key, end_key),
            ).fetchall()
            for row in rows:
                event = _event_from_index_payload(row[0])
                if event is None:
                    self.misses += 1
                    return None
                events.append(event)
        self.hits += len(fresh_paths)
        self.misses += len(missing)
        return events, supported_paths, unsupported_paths, missing

    def get_events_for_paths(
        self,
        paths: list[Path],
        signature: str,
    ) -> dict[Path, list[UsageEvent]]:
        stat_by_path: dict[str, os.stat_result] = {}
        path_by_text: dict[str, Path] = {}
        for path in paths:
            try:
                stat_by_path[str(path)] = path.stat()
            except OSError:
                continue
            path_by_text[str(path)] = path
        if not stat_by_path:
            self.misses += len(paths)
            return {}

        out: dict[Path, list[UsageEvent]] = {}
        for chunk in _chunks(list(stat_by_path), 500):
            placeholders = ",".join("?" for _ in chunk)
            rows = self._conn.execute(
                f"""
                select path, mtime_ns, size, payload from parsed_vendor_events
                where signature = ? and path in ({placeholders})
                """,  # nosec B608
                (signature, *chunk),
            ).fetchall()
            for path_text, mtime_ns, size, payload in rows:
                stat = stat_by_path.get(str(path_text))
                if stat is None or stat.st_mtime_ns != mtime_ns or stat.st_size != size:
                    continue
                events = _decode_events_payload(payload)
                if events is None:
                    continue
                out[path_by_text[str(path_text)]] = events
        self.hits += len(out)
        self.misses += max(0, len(paths) - len(out))
        return out

    def put_indexed_events(
        self,
        path: Path,
        signature: str,
        events: list[UsageEvent],
        *,
        vendor: str,
        unsupported: bool = False,
    ) -> None:
        self.put_records(
            path,
            signature,
            [ParsedSessionRecord(event=event) for event in events],
            vendor=vendor,
            unsupported=unsupported,
        )

    def indexed_stats(self) -> dict[str, int]:
        row = self._conn.execute(
            """
            select count(*), coalesce(sum(event_count), 0), coalesce(sum(sample_count), 0),
                   coalesce(sum(unsupported), 0)
            from indexed_parse_files
            """
        ).fetchone()
        return {
            "files": int(row[0] or 0),
            "events": int(row[1] or 0),
            "samples": int(row[2] or 0),
            "unsupported_files": int(row[3] or 0),
        }

    def indexed_file_counts(self, path: Path, signature: str) -> tuple[int, int, bool] | None:
        if not self._indexed_file_is_fresh(path, signature):
            return None
        row = self._conn.execute(
            """
            select event_count, sample_count, unsupported from indexed_parse_files
            where path = ? and signature = ?
            """,
            (str(path), signature),
        ).fetchone()
        if row is None:
            return None
        return int(row[0] or 0), int(row[1] or 0), bool(row[2])

    def _indexed_file_is_fresh(self, path: Path, signature: str) -> bool:
        try:
            stat = path.stat()
        except OSError:
            return False
        row = self._conn.execute(
            """
            select mtime_ns, size from indexed_parse_files
            where path = ? and signature = ?
            """,
            (str(path), signature),
        ).fetchone()
        return bool(row and row[0] == stat.st_mtime_ns and row[1] == stat.st_size)

    def _replace_indexed_rows(
        self,
        path: Path,
        signature: str,
        *,
        vendor: str,
        stat: os.stat_result,
        event_rows: list[tuple],
        sample_rows: list[tuple],
        unsupported: bool,
        timestamps: list[str],
    ) -> None:
        with self._conn:
            self._conn.execute(
                "delete from indexed_parse_events where path = ? and signature = ?",
                (str(path), signature),
            )
            self._conn.execute(
                "delete from indexed_parse_samples where path = ? and signature = ?",
                (str(path), signature),
            )
            self._conn.execute(
                """
                insert or replace into indexed_parse_files
                    (path, signature, vendor, mtime_ns, size, event_count, sample_count,
                     unsupported, min_timestamp, max_timestamp, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(path),
                    signature,
                    vendor,
                    stat.st_mtime_ns,
                    stat.st_size,
                    len(event_rows),
                    len(sample_rows),
                    int(unsupported),
                    min(timestamps) if timestamps else "",
                    max(timestamps) if timestamps else "",
                    _encode_datetime(dt.datetime.now(tz=dt.UTC)),
                ),
            )
            if event_rows:
                self._conn.executemany(
                    """
                    insert into indexed_parse_events
                        (path, signature, row_index, timestamp, counter_reset, payload)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    event_rows,
                )
            if sample_rows:
                self._conn.executemany(
                    """
                    insert into indexed_parse_samples
                        (path, signature, row_index, timestamp, payload)
                    values (?, ?, ?, ?, ?)
                    """,
                    sample_rows,
                )

    def stats(self) -> CacheStats:
        return CacheStats(path=self.path, hits=self.hits, misses=self.misses)

    def clear(self) -> int:
        """Drop every cached row across all tables and vacuum the file.

        Returns the number of rows removed. Exposed as `caliper cache clear`
        for users who want to force a re-parse or reclaim disk without
        removing the cache file by hand.
        """
        tables = (
            "parsed_sessions",
            "parsed_vendor_events",
            "indexed_parse_files",
            "indexed_parse_events",
            "indexed_parse_samples",
        )
        removed = 0
        with self._conn:
            for table in tables:
                cursor = self._conn.execute(f"delete from {table}")
                removed += cursor.rowcount if cursor.rowcount > 0 else 0
        self._conn.execute("vacuum")
        return removed

    def close(self) -> None:
        if self._closed:
            return
        self._conn.close()
        self._closed = True

    def __enter__(self) -> ParseCache:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except (AttributeError, sqlite3.Error):
            return


def _encode_datetime(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat()


def _decode_datetime(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value).astimezone(dt.UTC)


def _usage_to_dict(usage: Usage) -> dict:
    item = asdict(usage)
    item["cached_input_tokens"] = usage.cached_input_tokens
    return item


def _usage_from_dict(raw: dict) -> Usage:
    return Usage.from_dict(raw)


def _thread_to_dict(thread: ThreadMeta) -> dict:
    return asdict(thread)


def _thread_from_dict(raw: dict) -> ThreadMeta:
    return ThreadMeta(**{key: value for key, value in raw.items() if key in THREAD_META_FIELDS})


def _event_to_dict(event: UsageEvent) -> dict:
    item = asdict(event)
    item["timestamp"] = _encode_datetime(event.timestamp)
    item["path"] = str(event.path)
    item["usage"] = _usage_to_dict(event.usage)
    item["thread"] = _thread_to_dict(event.thread)
    for key, value in list(item.items()):
        if isinstance(value, Decimal):
            item[key] = str(value)
    return item


def _event_from_dict(raw: dict) -> UsageEvent:
    item = dict(raw)
    item["timestamp"] = _decode_datetime(str(item["timestamp"]))
    item["path"] = Path(str(item["path"]))
    item["usage"] = _usage_from_dict(item["usage"])
    item["thread"] = _thread_from_dict(item["thread"])
    if item.get("vendor_reported_cost_usd") is not None:
        item["vendor_reported_cost_usd"] = Decimal(str(item["vendor_reported_cost_usd"]))
    if "turn_facts" in item:
        item["turn_facts"] = TurnFacts.from_dict(item["turn_facts"])
    return UsageEvent(**{key: value for key, value in item.items() if key in USAGE_EVENT_FIELDS})


def _sample_to_dict(sample: RateLimitSample) -> dict:
    item = asdict(sample)
    item["timestamp"] = _encode_datetime(sample.timestamp)
    item["path"] = str(sample.path)
    return item


def _sample_from_dict(raw: dict) -> RateLimitSample:
    item = dict(raw)
    item["timestamp"] = _decode_datetime(str(item["timestamp"]))
    item["path"] = Path(str(item["path"]))
    sample_fields = {field.name for field in fields(RateLimitSample)}
    return RateLimitSample(**{key: value for key, value in item.items() if key in sample_fields})


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
    payload = _payload_from_json(raw)
    if payload is None:
        return None
    records = payload.get("records")
    if not isinstance(records, list):
        return None
    return _records_from_payload(records)


def _payload_from_json(raw) -> dict | None:
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = json.loads(text)
    except (AttributeError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return None
    return payload


def _records_from_payload(records: list) -> list[ParsedSessionRecord] | None:
    try:
        return [_record_from_dict(record) for record in records]
    except (KeyError, TypeError, ValueError):
        return None


def _record_from_dict(record: object) -> ParsedSessionRecord:
    if not isinstance(record, dict):
        raise TypeError("cached record must be an object")
    event_raw = record.get("event")
    sample_raw = record.get("sample")
    return ParsedSessionRecord(
        event=_event_from_dict(event_raw) if isinstance(event_raw, dict) else None,
        counter_reset=bool(record.get("reset")),
        sample=_sample_from_dict(sample_raw) if isinstance(sample_raw, dict) else None,
    )


def _coerce_record(record) -> ParsedSessionRecord:
    if isinstance(record, ParsedSessionRecord):
        return record
    event, reset, sample = record
    return ParsedSessionRecord(event=event, counter_reset=bool(reset), sample=sample)


def _encode_events_payload(events: list[UsageEvent]) -> bytes:
    payload = {
        "version": 1,
        "events": [_event_to_dict(event) for event in events],
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _decode_events_payload(raw) -> list[UsageEvent] | None:
    payload = _payload_from_json(raw)
    if payload is None:
        return None
    events = payload.get("events")
    if not isinstance(events, list):
        return None
    try:
        return [_event_from_dict(event) for event in events if isinstance(event, dict)]
    except (KeyError, TypeError, ValueError):
        return None


def _encode_index_payload(item: dict) -> bytes:
    return json.dumps(item, separators=(",", ":")).encode("utf-8")


def _dict_from_index_payload(raw) -> dict | None:
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = json.loads(text)
    except (AttributeError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _event_from_index_payload(raw) -> UsageEvent | None:
    payload = _dict_from_index_payload(raw)
    if payload is None:
        return None
    try:
        return _event_from_dict(payload)
    except (KeyError, TypeError, ValueError):
        return None


def _chunks(values: list[str], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _sample_from_index_payload(raw) -> RateLimitSample | None:
    payload = _dict_from_index_payload(raw)
    if payload is None:
        return None
    try:
        return _sample_from_dict(payload)
    except (KeyError, TypeError, ValueError):
        return None
