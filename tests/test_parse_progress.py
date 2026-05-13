"""Verify the optional ParseProgress callback is invoked correctly.

The default ``None`` path keeps load_usage byte-identical with the
existing CLI behaviour. The opt-in path emits ``starting`` once,
``file_done`` / ``cache_hit`` per file, and ``finished`` once.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from caliper.parser import load_usage
from caliper.progress import NULL_PROGRESS, NullProgress


@dataclass
class RecordingProgress:
    started: list[int] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    cached: list[Path] = field(default_factory=list)
    finished_count: int = 0

    def starting(self, total_files: int) -> None:
        self.started.append(total_files)

    def file_done(self, path: Path) -> None:
        self.files.append(path)

    def cache_hit(self, path: Path) -> None:
        self.cached.append(path)

    def finished(self) -> None:
        self.finished_count += 1


def test_null_progress_methods_return_none():
    null = NullProgress()
    assert null.starting(10) is None
    assert null.file_done(Path("/tmp/x")) is None
    assert null.cache_hit(Path("/tmp/y")) is None
    assert null.finished() is None


def test_null_progress_singleton_is_protocol_compatible():
    assert hasattr(NULL_PROGRESS, "starting")
    assert hasattr(NULL_PROGRESS, "file_done")
    assert hasattr(NULL_PROGRESS, "cache_hit")
    assert hasattr(NULL_PROGRESS, "finished")


def test_load_usage_default_progress_does_not_crash(tmp_path, monkeypatch):
    from caliper.config import build_options

    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        session_root=tmp_path / "codex",
        state_db=tmp_path / "state.db",
        codex_config=tmp_path / "codex.toml",
        since="2026-04-01",
        until="2026-05-01",
    )
    load_usage(options)  # default progress=NULL_PROGRESS


def test_load_usage_records_starting_and_finished(tmp_path, monkeypatch):
    from caliper.config import build_options

    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        session_root=tmp_path / "codex",
        state_db=tmp_path / "state.db",
        codex_config=tmp_path / "codex.toml",
        since="2026-04-01",
        until="2026-05-01",
    )
    progress = RecordingProgress()
    load_usage(options, progress=progress)
    assert progress.started == [0]
    assert progress.finished_count == 1
    assert progress.files == []
    assert progress.cached == []


def test_load_usage_emits_file_done_for_each_session(tmp_path, monkeypatch):
    """When the session root has real JSONL, file_done fires per file."""
    from caliper.config import build_options
    from tests.conftest import token_event, write_session  # type: ignore[import-not-found]

    codex_root = tmp_path / "codex"
    codex_root.mkdir()

    write_session(
        codex_root,
        "abc123.jsonl",
        [
            token_event(
                dt.datetime(2026, 4, 15, 12, 0, tzinfo=dt.UTC),
                {"input_tokens": 100, "output_tokens": 50},
            ),
        ],
    )

    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path / "aider"))
    monkeypatch.setenv("CALIPER_CURSOR_HOME", str(tmp_path / "cursor"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        session_root=codex_root,
        state_db=tmp_path / "state.db",
        codex_config=tmp_path / "codex.toml",
        since="2026-04-01",
        until="2026-05-01",
        no_parse_cache=True,
    )
    progress = RecordingProgress()
    load_usage(options, progress=progress)
    assert progress.started == [1]
    assert len(progress.files) == 1
    assert "abc123" in str(progress.files[0])
    assert progress.finished_count == 1
