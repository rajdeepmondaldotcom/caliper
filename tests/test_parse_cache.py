from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from codex_meter import parser
from codex_meter.config import build_options
from codex_meter.models import ParsedSessionRecord, RateLimitSample, ThreadMeta, Usage, UsageEvent
from codex_meter.parse_cache import (
    ParseCache,
    _decode_payload,
    _encode_payload,
    _event_from_dict,
    _thread_from_dict,
    default_cache_path,
)

from .conftest import make_state_db, token_event, turn_context, write_session


def _fixture(tmp_path) -> tuple:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-cache.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(now, {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=state_db,
        codex_config=tmp_path / "missing.toml",
    )
    return options


def test_parse_cache_reuses_parsed_session(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_METER_CACHE_DIR", str(tmp_path / "cache"))
    options = _fixture(tmp_path)
    first = parser.load_usage(options)
    assert len(first.events) == 1

    def fail_parse(*_args, **_kwargs):
        raise AssertionError("cache miss")

    monkeypatch.setattr(parser, "_parse_session", fail_parse)
    second = parser.load_usage(options)
    assert len(second.events) == 1
    assert second.events[0].usage.input_tokens == 100


def test_parse_cache_reuses_session_across_different_windows(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_METER_CACHE_DIR", str(tmp_path / "cache"))
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-cache-window.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(now, {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}),
            token_event(
                now + dt.timedelta(minutes=10),
                {"input_tokens": 200, "output_tokens": 20, "total_tokens": 220},
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    first_options = build_options(
        since=(now - dt.timedelta(minutes=1)).isoformat(),
        until=(now + dt.timedelta(minutes=20)).isoformat(),
        session_root=session_root,
        state_db=state_db,
        codex_config=tmp_path / "missing.toml",
    )
    assert len(parser.load_usage(first_options).events) == 2

    second_options = build_options(
        since=(now + dt.timedelta(minutes=5)).isoformat(),
        until=(now + dt.timedelta(minutes=20)).isoformat(),
        session_root=session_root,
        state_db=state_db,
        codex_config=tmp_path / "missing.toml",
    )

    def fail_parse(*_args, **_kwargs):
        raise AssertionError("cache miss")

    monkeypatch.setattr(parser, "_parse_session", fail_parse)
    second = parser.load_usage(second_options)
    assert [event.usage.input_tokens for event in second.events] == [200]


def test_no_parse_cache_bypasses_existing_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_METER_CACHE_DIR", str(tmp_path / "cache"))
    options = _fixture(tmp_path)
    assert parser.load_usage(options).events

    uncached = build_options(
        days=1,
        until=options.end.isoformat(),
        session_root=options.session_root,
        state_db=options.state_db,
        codex_config=options.config_path,
        no_parse_cache=True,
    )

    def fail_parse(*_args, **_kwargs):
        raise RuntimeError("cache disabled")

    monkeypatch.setattr(parser, "_parse_session", fail_parse)
    with pytest.raises(RuntimeError, match="cache disabled"):
        parser.load_usage(uncached)


def test_parse_cache_ignores_legacy_or_invalid_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_METER_CACHE_DIR", str(tmp_path / "cache"))
    options = _fixture(tmp_path)
    path = next(iter(parser.session_files(options.session_root)))
    cache = ParseCache.default()
    signature = parser._parse_cache_signature(
        options,
        parser.current_config_service_tier(options.config_path),
        parser.load_tier_overrides(options.tier_overrides),
        parser.load_thread_metadata(options.state_db)[str(path)],
    )
    stat = path.stat()
    with closing(sqlite3.connect(default_cache_path())) as conn, conn:
        conn.execute(
            """
            insert or replace into parsed_sessions
                (path, signature, mtime_ns, size, byte_offset, payload)
            values (?, ?, ?, ?, ?, ?)
            """,
            (str(path), signature, stat.st_mtime_ns, stat.st_size, stat.st_size, b"not-json"),
        )

    assert cache.get(path, signature) is None
    assert cache.stats().misses == 1


def test_parse_cache_round_trips_named_records() -> None:
    event = UsageEvent(
        timestamp=dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
        path=Path("/tmp/session.jsonl"),
        session_id="session",
        usage=Usage(input_tokens=1, total_tokens=1),
        model="gpt-5.5",
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(cwd="/tmp/project"),
    )
    sample = RateLimitSample(
        timestamp=event.timestamp,
        path=event.path,
        session_id=event.session_id,
        primary_used_percent=12.5,
    )

    payload = _encode_payload([ParsedSessionRecord(event=event, counter_reset=True, sample=sample)])
    decoded = _decode_payload(payload)

    assert decoded is not None
    assert decoded[0].event is not None
    assert decoded[0].event.model == "gpt-5.5"
    assert decoded[0].counter_reset is True
    assert decoded[0].sample is not None
    assert decoded[0].sample.primary_used_percent == 12.5


def test_parse_cache_thread_decode_ignores_future_metadata_keys() -> None:
    thread = _thread_from_dict({"cwd": "/tmp/project", "future_field": "ignored"})

    assert thread.cwd == "/tmp/project"


def test_parse_cache_event_decode_ignores_future_metadata_keys() -> None:
    event = _event_from_dict(
        {
            "timestamp": "2026-05-12T00:00:00+00:00",
            "path": "/tmp/session.jsonl",
            "session_id": "session",
            "usage": {"input_tokens": 1, "total_tokens": 1},
            "model": "gpt-5.5",
            "service_tier": "standard",
            "tier_source": "logged",
            "thread": {"cwd": "/tmp/project"},
            "model_source": "turn_context",
            "model_is_fallback": False,
            "future_event_key": "ignored",
        }
    )

    assert event.model == "gpt-5.5"
    assert event.model_source == "turn_context"
