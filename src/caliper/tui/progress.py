"""Bridge between :class:`caliper.progress.ParseProgress` and Textual.

The CLI uses ``NullProgress`` and observes no UI updates. The TUI's
``load_usage_worker`` constructs a :class:`TextualParseProgress` that
forwards every event as a thread-safe ``post_message`` call.

Worker cancellation is cooperative: each callback checks the active
worker's ``is_cancelled`` flag and raises :class:`WorkerCancelled` to
unwind the parser cleanly. The worker handles the exception and posts
:class:`caliper.tui.messages.LoadCancelled`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.worker import get_current_worker

from caliper.tui.messages import (
    LoadFileCacheHit,
    LoadFileDone,
    LoadFinished,
    LoadStarted,
    WorkerCancelled,
)

if TYPE_CHECKING:  # pragma: no cover
    from textual.app import App


class TextualParseProgress:
    """ParseProgress implementation that talks to the Textual message bus."""

    def __init__(self, app: App) -> None:
        self._app = app
        self._worker = None  # resolved lazily inside the worker thread

    def _ensure_worker(self) -> None:
        if self._worker is None:
            self._worker = get_current_worker()

    def starting(self, total_files: int) -> None:
        self._ensure_worker()
        self._app.post_message(LoadStarted(total_files))

    def file_done(self, path: Path) -> None:
        self._ensure_worker()
        if self._worker is not None and self._worker.is_cancelled:
            raise WorkerCancelled
        self._app.post_message(LoadFileDone(path))

    def cache_hit(self, path: Path) -> None:
        self._ensure_worker()
        if self._worker is not None and self._worker.is_cancelled:
            raise WorkerCancelled
        self._app.post_message(LoadFileCacheHit(path))

    def finished(self) -> None:
        self._app.post_message(LoadFinished())
