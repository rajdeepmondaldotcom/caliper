"""Verify TextualParseProgress respects worker cancellation."""

from __future__ import annotations

from pathlib import Path

import pytest

from caliper.tui.messages import WorkerCancelled
from caliper.tui.progress import TextualParseProgress


class _StubApp:
    def __init__(self):
        self.messages: list = []

    def post_message(self, message) -> None:
        self.messages.append(message)


class _StubWorker:
    def __init__(self, cancelled: bool = False):
        self.is_cancelled = cancelled


def test_file_done_raises_when_worker_cancelled(monkeypatch):
    monkeypatch.setattr(
        "caliper.tui.progress.get_current_worker",
        lambda: _StubWorker(cancelled=True),
    )
    progress = TextualParseProgress(_StubApp())
    with pytest.raises(WorkerCancelled):
        progress.file_done(Path("/tmp/x"))


def test_cache_hit_raises_when_worker_cancelled(monkeypatch):
    monkeypatch.setattr(
        "caliper.tui.progress.get_current_worker",
        lambda: _StubWorker(cancelled=True),
    )
    progress = TextualParseProgress(_StubApp())
    with pytest.raises(WorkerCancelled):
        progress.cache_hit(Path("/tmp/y"))


def test_progress_forwards_when_not_cancelled(monkeypatch):
    monkeypatch.setattr(
        "caliper.tui.progress.get_current_worker",
        lambda: _StubWorker(cancelled=False),
    )
    app = _StubApp()
    progress = TextualParseProgress(app, min_interval=0.0)
    progress.starting(3)
    progress.file_done(Path("/a"))
    progress.cache_hit(Path("/b"))
    progress.finished()
    types = [type(message).__name__ for message in app.messages]
    assert types == [
        "LoadStarted",
        "LoadProgress",
        "LoadProgress",
        "LoadProgress",
        "LoadProgress",
        "LoadFinished",
    ]
    assert app.messages[-2].done == 1
    assert app.messages[-2].cached == 1


def test_progress_coalesces_file_updates(monkeypatch):
    monkeypatch.setattr(
        "caliper.tui.progress.get_current_worker",
        lambda: _StubWorker(cancelled=False),
    )
    app = _StubApp()
    progress = TextualParseProgress(app, min_interval=60.0)
    progress.starting(100)
    for index in range(10):
        progress.file_done(Path(f"/tmp/{index}"))

    types = [type(message).__name__ for message in app.messages]
    assert types == ["LoadStarted", "LoadProgress"]
