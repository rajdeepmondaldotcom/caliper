"""The Claude Code parser skips files whose mtime predates the window start.

A file last modified before the window can't hold in-window events, so reading
it is wasted work. This pins the optimisation's safety: a fresh in-window file
is still fully read (we never drop real data), and the skip path doesn't error.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
from pathlib import Path

from caliper.config import build_options
from caliper.parser import load_usage

FIXTURE = Path(__file__).parent / "fixtures" / "claude_code" / "example.jsonl"


def _opts(since: str, until: str):
    # The Claude Code parser discovers logs under $CLAUDE_CONFIG_DIR (set by the
    # test via monkeypatch).
    return build_options(since=since, until=until, vendors=["claude-code"], no_parse_cache=True)


def _install_fixture(root: Path) -> Path:
    dest = root / "projects" / "proj" / "session.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, dest)
    return dest


def test_fresh_in_window_file_is_read(tmp_path, monkeypatch) -> None:
    # Fixture events are dated 2026-05-12; a fresh mtime + a window covering that
    # date must yield the event (filter must not over-skip).
    root = tmp_path / "claude"
    dest = _install_fixture(root)
    now = dt.datetime.now(tz=dt.UTC).timestamp()
    os.utime(dest, (now, now))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root))

    result = load_usage(_opts(since="2026-05-10", until="2026-05-20"))
    assert len(result.events) == 1, "in-window file must be parsed"
    assert result.events[0].usage.input_tokens == 350  # matches expected.json


def test_stale_mtime_file_is_skipped_without_error(tmp_path, monkeypatch) -> None:
    # Same fixture but mtime backdated well before the window start: the
    # pre-filter skips the read. Returns cleanly with no events (the mtime skip
    # is a sound lower bound — a file written in 2024 holds no 2026 events).
    root = tmp_path / "claude"
    dest = _install_fixture(root)
    old = dt.datetime(2024, 1, 1, tzinfo=dt.UTC).timestamp()
    os.utime(dest, (old, old))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root))

    result = load_usage(_opts(since="2026-05-10", until="2026-05-20"))
    assert result.events == []
