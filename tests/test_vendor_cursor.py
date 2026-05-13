from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import closing

from caliper.config import build_options
from caliper.models import VENDOR_CURSOR
from caliper.parser import load_usage
from caliper.vendors.cursor import _cursor_root


def test_cursor_vscdb_fixture_round_trip(monkeypatch, tmp_path) -> None:
    root = tmp_path / "cursor"
    db = root / "User" / "globalStorage" / "state.vscdb"
    db.parent.mkdir(parents=True)
    timestamp = dt.datetime(2026, 5, 12, tzinfo=dt.UTC).isoformat().replace("+00:00", "Z")
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(
            """
            create table cursor_usage (
                timestamp text, session_id text, cwd text, model text, input_tokens integer,
                cached_input_tokens integer, output_tokens integer, total_tokens integer
            )
            """
        )
        conn.execute(
            "insert into cursor_usage values (?, ?, ?, ?, ?, ?, ?, ?)",
            (timestamp, "cursor-session", "/tmp/project-alpha", "cursor-auto", 100, 20, 10, 110),
        )
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(root))
    options = build_options(
        since="2026-05-12T00:00:00Z",
        until="2026-05-13T00:00:00Z",
        session_root=tmp_path / "missing-codex",
        vendors=[VENDOR_CURSOR],
    )

    result = load_usage(options)

    assert len(result.events) == 1
    assert result.events[0].vendor == VENDOR_CURSOR
    assert result.events[0].usage.total_tokens == 110


def test_cursor_vscdb_kv_usage_round_trip(monkeypatch, tmp_path) -> None:
    root = tmp_path / "cursor"
    db = root / "User" / "workspaceStorage" / "workspace-a" / "state.vscdb"
    db.parent.mkdir(parents=True)
    timestamp = dt.datetime(2026, 5, 12, tzinfo=dt.UTC).isoformat().replace("+00:00", "Z")
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("create table ItemTable (key text, value blob)")
        conn.execute(
            "insert into ItemTable values (?, ?)",
            (
                "cursor.usage.event",
                json.dumps(
                    {
                        "timestamp": timestamp,
                        "sessionId": "kv-session",
                        "cwd": "/tmp/project-alpha",
                        "model": "cursor-auto",
                        "usage": {
                            "input_tokens": 80,
                            "cached_input_tokens": 8,
                            "output_tokens": 12,
                            "total_tokens": 92,
                        },
                        "message": {"content": "private prompt must not be parsed"},
                    }
                ),
            ),
        )
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(root))
    options = build_options(
        since="2026-05-12T00:00:00Z",
        until="2026-05-13T00:00:00Z",
        session_root=tmp_path / "missing-codex",
        vendors=[VENDOR_CURSOR],
    )

    result = load_usage(options)

    assert len(result.events) == 1
    assert result.events[0].usage_source == "cursor-kv-json"
    assert result.events[0].usage.total_tokens == 92
    assert result.parser_issues == []
    assert result.vendor_stats[VENDOR_CURSOR].files_with_events == 1


def test_cursor_root_defaults_when_no_override(monkeypatch) -> None:
    monkeypatch.delenv("CALIPER_CURSOR_HOME", raising=False)

    assert _cursor_root().name == "Cursor"


def test_cursor_jsonl_fixture_round_trip(monkeypatch, tmp_path) -> None:
    root = tmp_path / "cursor"
    project = root / "projects" / "project-alpha" / "session.jsonl"
    project.parent.mkdir(parents=True)
    project.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-12T00:00:00Z",
                "sessionId": "cursor-json",
                "cwd": "/tmp/project-alpha",
                "model": "cursor-auto",
                "usage": {"input_tokens": 50, "output_tokens": 5, "total_tokens": 55},
            }
        )
        + "\n"
    )
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(root))
    options = build_options(
        since="2026-05-12T00:00:00Z",
        until="2026-05-13T00:00:00Z",
        session_root=tmp_path / "missing-codex",
        vendors=[VENDOR_CURSOR],
    )

    result = load_usage(options)

    assert len(result.events) == 1
    assert result.events[0].usage.input_tokens == 50


def test_cursor_transcript_only_files_are_structured_unsupported(monkeypatch, tmp_path) -> None:
    root = tmp_path / "cursor"
    project = root / "projects" / "project-alpha" / "session.jsonl"
    project.parent.mkdir(parents=True)
    project.write_text(
        json.dumps({"role": "assistant", "message": {"content": ["no token counts here"]}}) + "\n"
    )
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(root))
    options = build_options(
        since="2026-05-12T00:00:00Z",
        until="2026-05-13T00:00:00Z",
        session_root=tmp_path / "missing-codex",
        vendors=[VENDOR_CURSOR],
    )

    result = load_usage(options)

    assert result.events == []
    assert result.parser_issues[0].kind == "unsupported:no_token_usage"
    assert result.parser_issues[0].count == 1
    assert "Cursor files have no per-event token counts" in result.warnings[0]
    assert result.vendor_stats[VENDOR_CURSOR].unsupported_files == 1


def test_cursor_unsupported_files_are_cached(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CALIPER_CACHE_DIR", str(tmp_path / "cache"))
    root = tmp_path / "cursor"
    project = root / "projects" / "project-alpha" / "session.jsonl"
    project.parent.mkdir(parents=True)
    project.write_text(
        json.dumps({"role": "assistant", "message": {"content": ["no token counts here"]}}) + "\n"
    )
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(root))
    options = build_options(
        since="2026-05-12T00:00:00Z",
        until="2026-05-13T00:00:00Z",
        session_root=tmp_path / "missing-codex",
        vendors=[VENDOR_CURSOR],
    )

    first = load_usage(options)
    assert first.vendor_stats[VENDOR_CURSOR].unsupported_files == 1

    def explode(*_args, **_kwargs):  # pragma: no cover - only called on cache miss
        raise AssertionError("Cursor transcript-only file was reparsed instead of cached")

    monkeypatch.setattr("caliper.vendors.cursor.parse_project_jsonl", explode)
    second = load_usage(options)

    assert second.events == []
    assert second.vendor_stats[VENDOR_CURSOR].unsupported_files == 1


def test_cursor_out_of_window_file_does_not_create_parser_warning(monkeypatch, tmp_path) -> None:
    root = tmp_path / "cursor"
    project = root / "projects" / "project-alpha" / "session.jsonl"
    project.parent.mkdir(parents=True)
    project.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-10T00:00:00Z",
                "sessionId": "cursor-json",
                "cwd": "/tmp/project-alpha",
                "model": "cursor-auto",
                "usage": {"input_tokens": 50, "output_tokens": 5, "total_tokens": 55},
            }
        )
        + "\n"
    )
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(root))
    options = build_options(
        since="2026-05-12T00:00:00Z",
        until="2026-05-13T00:00:00Z",
        session_root=tmp_path / "missing-codex",
        vendors=[VENDOR_CURSOR],
    )

    result = load_usage(options)

    assert result.events == []
    assert result.warnings == []
