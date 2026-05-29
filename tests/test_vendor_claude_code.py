from __future__ import annotations

import json
from pathlib import Path

from caliper.config import build_options
from caliper.models import VENDOR_CLAUDE_CODE
from caliper.parser import load_usage


def test_claude_code_fixture_round_trip(monkeypatch, tmp_path) -> None:
    fixture = Path("tests/fixtures/claude_code/example.jsonl")
    expected = json.loads(Path("tests/fixtures/claude_code/expected.json").read_text())
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    (projects / "claude-session-1.jsonl").write_text(fixture.read_text())
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = build_options(
        since="2026-05-12T00:00:00Z",
        until="2026-05-13T00:00:00Z",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
    )

    result = load_usage(options)

    assert len(result.events) == expected["events"]
    event = result.events[0]
    assert event.vendor == expected["vendor"]
    assert event.model == expected["model"]
    assert event.thread.git_branch == expected["git_branch"]
    assert event.usage.input_tokens == expected["input_tokens"]
    assert event.usage.cache_creation_input_tokens == expected["cache_creation_input_tokens"]
    assert event.usage.cache_read_input_tokens == expected["cache_read_input_tokens"]
    assert event.usage.cached_input_tokens == expected["cached_input_tokens"]
    assert event.usage.output_tokens == expected["output_tokens"]
    assert event.usage.total_tokens == expected["total_tokens"]
    assert "private prompt" not in repr(event)


def test_claude_code_cache_is_independent_of_report_window(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CALIPER_CACHE_DIR", str(tmp_path / "cache"))
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    session = projects / "claude-session-1.jsonl"
    session.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "claude-session-1",
                        "timestamp": "2026-05-12T10:00:00.000Z",
                        "cwd": "/tmp/project-alpha",
                        "message": {
                            "role": "assistant",
                            "model": "claude-sonnet-4-6-20260501",
                            "usage": {"input_tokens": 100, "output_tokens": 10},
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "claude-session-1",
                        "timestamp": "2026-05-12T12:00:00.000Z",
                        "cwd": "/tmp/project-alpha",
                        "message": {
                            "role": "assistant",
                            "model": "claude-sonnet-4-6-20260501",
                            "usage": {"input_tokens": 200, "output_tokens": 20},
                        },
                    }
                ),
            ]
        )
        + "\n"
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    base = {
        "session_root": tmp_path / "missing-codex",
        "state_db": tmp_path / "missing-state.sqlite",
        "codex_config": tmp_path / "missing-config.toml",
        "vendors": [VENDOR_CLAUDE_CODE],
    }
    warm_options = build_options(
        since="2026-05-12T00:00:00Z",
        until="2026-05-13T00:00:00Z",
        **base,
    )

    warmed = load_usage(warm_options)

    assert [event.usage.total_tokens for event in warmed.events] == [110, 220]

    def explode(*args, **kwargs):  # pragma: no cover - only called on cache miss
        raise AssertionError("Claude Code file was reparsed instead of read from cache")

    monkeypatch.setattr("caliper.vendors.claude_code._parse_session", explode)
    narrow_options = build_options(
        since="2026-05-12T11:00:00Z",
        until="2026-05-12T13:00:00Z",
        **base,
    )

    narrowed = load_usage(narrow_options)

    assert [event.usage.total_tokens for event in narrowed.events] == [220]


def test_claude_code_dedupes_message_request_pairs(monkeypatch, tmp_path) -> None:
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    row = {
        "type": "assistant",
        "sessionId": "claude-session-1",
        "timestamp": "2026-05-12T10:00:00.000Z",
        "cwd": "/tmp/project-alpha",
        "requestId": "req-1",
        "message": {
            "id": "msg-1",
            "role": "assistant",
            "model": "claude-sonnet-4-6-20260501",
            "usage": {
                "input_tokens": 100,
                "cache_creation_input_tokens": 50,
                "cache_read_input_tokens": 200,
                "output_tokens": 25,
            },
        },
    }
    session = projects / "claude-session-1.jsonl"
    session.write_text("\n".join(json.dumps(item) for item in [row, row]) + "\n")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        since="2026-05-12",
        until="2026-05-12",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )
    result = load_usage(options)

    assert len(result.events) == 1
    assert result.duplicates == 1
    event = result.events[0]
    assert event.message_id == "msg-1"
    assert event.request_id == "req-1"
    assert event.dedupe_key == "msg-1:req-1"
    assert event.raw_model == "claude-sonnet-4-6-20260501"
    assert event.source_line == 1
    assert event.usage.input_tokens == 350
    assert event.usage.cache_creation_input_tokens == 50
    assert event.usage.cache_read_input_tokens == 200


def test_claude_code_dedupes_message_request_even_when_event_ids_differ(
    monkeypatch, tmp_path
) -> None:
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    row = {
        "sessionId": "claude-session-1",
        "timestamp": "2026-05-12T10:00:00.000Z",
        "requestId": "req-1",
        "message": {
            "id": "msg-1",
            "model": "claude-sonnet-4-6-20260501",
            "usage": {"input_tokens": 100, "output_tokens": 25},
        },
    }
    first = {"uuid": "assistant-event-1", **row}
    second = {"uuid": "assistant-event-2", **row}
    (projects / "claude-session-1.jsonl").write_text(
        "\n".join(json.dumps(item) for item in [first, second]) + "\n"
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        since="2026-05-12",
        until="2026-05-12",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )
    result = load_usage(options)

    assert len(result.events) == 1
    assert result.duplicates == 1
    assert result.dedupe_stats == {"message_request": 1}


def test_claude_code_no_dedupe_is_ignored(monkeypatch, tmp_path) -> None:
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    row = {
        "sessionId": "claude-session-1",
        "timestamp": "2026-05-12T10:00:00.000Z",
        "requestId": "req-1",
        "message": {
            "id": "msg-1",
            "model": "claude-sonnet-4-6-20260501",
            "usage": {"input_tokens": 100, "output_tokens": 25},
        },
    }
    (projects / "claude-session-1.jsonl").write_text(
        "\n".join(json.dumps(item) for item in [row, row]) + "\n"
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        since="2026-05-12",
        until="2026-05-12",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_dedupe=True,
        no_parse_cache=True,
    )
    result = load_usage(options)

    assert options.dedupe is True
    assert len(result.events) == 1
    assert result.duplicates == 1


def test_claude_turn_latency_from_preceding_event(tmp_path) -> None:
    from caliper.config import build_options as _bo
    from caliper.vendors.claude_code import _parse_session

    session = tmp_path / "session.jsonl"
    rows = [
        # User prompt at 10:00:00; the reply lands 3s later → latency 3000ms.
        {"type": "user", "sessionId": "s1", "timestamp": "2026-05-12T10:00:00.000Z"},
        {
            "type": "assistant",
            "sessionId": "s1",
            "timestamp": "2026-05-12T10:00:03.000Z",
            "message": {
                "id": "m1",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        },
        # A gap of 20 minutes reads as idle time → latency dropped (None).
        {"type": "user", "sessionId": "s1", "timestamp": "2026-05-12T11:00:00.000Z"},
        {
            "type": "assistant",
            "sessionId": "s1",
            "timestamp": "2026-05-12T11:20:00.000Z",
            "message": {
                "id": "m2",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        },
    ]
    session.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    options = _bo(timezone="UTC", vendors=[VENDOR_CLAUDE_CODE], no_parse_cache=True)
    events = _parse_session(session, options)
    assert len(events) == 2
    assert events[0].turn_facts.latency_ms == 3000
    assert events[1].turn_facts.latency_ms is None


def test_claude_tool_result_outcomes_attach_to_turn(tmp_path) -> None:
    from caliper.config import build_options as _bo
    from caliper.vendors.claude_code import _parse_session

    session = tmp_path / "session.jsonl"
    rows = [
        {
            "type": "assistant",
            "sessionId": "s1",
            "timestamp": "2026-05-12T10:00:00.000Z",
            "message": {
                "id": "m1",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 100, "output_tokens": 20},
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Edit", "input": {}},
                    {"type": "tool_use", "id": "t2", "name": "Bash", "input": {}},
                ],
            },
        },
        # Tool results arrive in the following user event(s), keyed by tool_use_id.
        {
            "type": "user",
            "sessionId": "s1",
            "timestamp": "2026-05-12T10:00:05.000Z",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False}],
            },
            "toolUseResult": {
                "structuredPatch": [
                    {"lines": ["+added one", "+added two", "-removed one", " context"]}
                ]
            },
        },
        {
            "type": "user",
            "sessionId": "s1",
            "timestamp": "2026-05-12T10:00:06.000Z",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t2", "is_error": True}],
            },
        },
    ]
    session.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    options = _bo(timezone="UTC", vendors=[VENDOR_CLAUDE_CODE], no_parse_cache=True)
    events = _parse_session(session, options)
    assert len(events) == 1
    facts = events[0].turn_facts
    assert facts.tool_result_count == 2
    assert facts.tool_error_count == 1  # the Bash result errored
    assert facts.lines_added == 2
    assert facts.lines_removed == 1
