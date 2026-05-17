from __future__ import annotations

import json

from caliper.config import build_options
from caliper.models import VENDOR_CLAUDE_CODE
from caliper.parser import load_usage

SECRET = "REDACTED_SECRET_THAT_MUST_NEVER_LEAK"


def _write_session(tmp_path, rows):
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    (projects / "claude-session-1.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )
    return projects


def _options(tmp_path):
    return build_options(
        since="2026-05-12",
        until="2026-05-13",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )


def _base_row(*, line_number: int, content):
    return {
        "type": "assistant",
        "sessionId": "claude-session-1",
        "parentUuid": f"parent-{line_number}",
        "uuid": f"event-{line_number}",
        "timestamp": f"2026-05-12T10:{line_number:02d}:00.000Z",
        "cwd": "/tmp/project-alpha",
        "requestId": f"req-{line_number}",
        "message": {
            "id": f"msg-{line_number}",
            "role": "assistant",
            "model": "claude-sonnet-4-6-20260501",
            "content": content,
            "usage": {"input_tokens": 100 + line_number, "output_tokens": 25},
        },
    }


def test_tool_use_blocks_are_counted(monkeypatch, tmp_path) -> None:
    _write_session(
        tmp_path,
        [
            _base_row(
                line_number=1,
                content=[
                    {"type": "thinking", "thinking": SECRET},
                    {"type": "tool_use", "name": "Read", "input": {"file": SECRET}},
                    {"type": "tool_use", "name": "Edit", "input": {"path": SECRET}},
                ],
            ),
            _base_row(
                line_number=2,
                content=[
                    {"type": "text", "text": SECRET},
                    {"type": "tool_use", "name": "Bash", "input": {"command": SECRET}},
                ],
            ),
        ],
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    result = load_usage(_options(tmp_path))

    events = sorted(result.events, key=lambda event: event.timestamp)
    assert len(events) == 2
    first, second = events
    assert first.turn_facts is not None
    assert first.turn_facts.tool_use_count == 2
    assert first.turn_facts.tool_names == ("Edit", "Read")
    assert first.turn_facts.has_thinking_block is True
    assert first.turn_facts.parent_uuid == "parent-1"
    assert first.turn_facts.turn_index == 0
    assert second.turn_facts is not None
    assert second.turn_facts.tool_use_count == 1
    assert second.turn_facts.tool_names == ("Bash",)
    assert second.turn_facts.has_thinking_block is False
    assert second.turn_facts.turn_index == 1


def test_tool_use_input_is_never_captured(monkeypatch, tmp_path) -> None:
    _write_session(
        tmp_path,
        [
            _base_row(
                line_number=1,
                content=[
                    {"type": "tool_use", "name": "Bash", "input": {"command": SECRET}},
                    {"type": "text", "text": SECRET},
                    {"type": "thinking", "thinking": SECRET},
                ],
            ),
        ],
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    result = load_usage(_options(tmp_path))

    event = result.events[0]
    assert event.turn_facts is not None
    assert SECRET not in repr(event)
    assert SECRET not in repr(event.turn_facts)
    # No field on turn_facts should contain prompt content.
    for value in vars(event.turn_facts).values():
        assert SECRET not in repr(value)


def test_missing_content_yields_empty_turn_facts(monkeypatch, tmp_path) -> None:
    _write_session(
        tmp_path,
        [
            {
                "type": "assistant",
                "sessionId": "claude-session-1",
                "timestamp": "2026-05-12T10:00:00.000Z",
                "cwd": "/tmp/project-alpha",
                "requestId": "req-1",
                "message": {
                    "id": "msg-1",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6-20260501",
                    "usage": {"input_tokens": 100, "output_tokens": 25},
                },
            }
        ],
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    result = load_usage(_options(tmp_path))

    event = result.events[0]
    assert event.turn_facts is not None
    assert event.turn_facts.tool_use_count == 0
    assert event.turn_facts.tool_names == ()
    assert event.turn_facts.has_thinking_block is False


def test_turn_index_is_session_local(monkeypatch, tmp_path) -> None:
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    rows_a = [
        _base_row(line_number=n, content=[{"type": "tool_use", "name": "Read"}])
        for n in range(1, 4)
    ]
    rows_b = [
        {
            **_base_row(line_number=n, content=[{"type": "tool_use", "name": "Read"}]),
            "sessionId": "claude-session-2",
            "uuid": f"event-b-{n}",
            "requestId": f"req-b-{n}",
            "message": {
                **_base_row(line_number=n, content=[]).get("message", {}),
                "id": f"msg-b-{n}",
            },
        }
        for n in range(1, 3)
    ]
    # rewrite the b rows' message content to have a tool_use block
    for row in rows_b:
        row["message"]["content"] = [{"type": "tool_use", "name": "Read"}]
    (projects / "session-a.jsonl").write_text("\n".join(json.dumps(r) for r in rows_a) + "\n")
    (projects / "session-b.jsonl").write_text("\n".join(json.dumps(r) for r in rows_b) + "\n")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    result = load_usage(_options(tmp_path))

    by_session: dict[str, list[int]] = {}
    for event in result.events:
        assert event.turn_facts is not None
        by_session.setdefault(event.session_id, []).append(event.turn_facts.turn_index)

    assert sorted(by_session["claude-session-1"]) == [0, 1, 2]
    assert sorted(by_session["claude-session-2"]) == [0, 1]
