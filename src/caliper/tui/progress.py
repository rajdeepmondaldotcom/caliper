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
from time import monotonic
from typing import TYPE_CHECKING

from textual.worker import get_current_worker

from caliper.tui.messages import (
    LoadFinished,
    LoadProgress,
    LoadStarted,
    WorkerCancelled,
)

if TYPE_CHECKING:  # pragma: no cover
    from textual.app import App


class TextualParseProgress:
    """ParseProgress implementation that talks to the Textual message bus."""

    def __init__(self, app: App, *, generation: int = 0, min_interval: float = 0.1) -> None:
        self._app = app
        self._generation = generation
        self._min_interval = min_interval
        self._worker = None  # resolved lazily inside the worker thread
        self._total = 0
        self._done = 0
        self._cached = 0
        self._stage = "discovering"
        self._last_emit = 0.0

    def _ensure_worker(self) -> None:
        if self._worker is None:
            self._worker = get_current_worker()

    def _check_cancelled(self) -> None:
        self._ensure_worker()
        if self._worker is not None and self._worker.is_cancelled:
            raise WorkerCancelled

    def _emit(self, *, force: bool = False) -> None:
        now = monotonic()
        if not force and now - self._last_emit < self._min_interval:
            return
        self._last_emit = now
        self._app.post_message(
            LoadProgress(
                total=self._total,
                done=self._done,
                cached=self._cached,
                stage=self._stage,
                generation=self._generation,
            )
        )

    def starting(self, total_files: int) -> None:
        self._check_cancelled()
        self._total = total_files
        self._stage = "reading"
        self._app.post_message(LoadStarted(total_files, generation=self._generation))
        self._emit(force=True)

    def file_done(self, path: Path) -> None:
        del path
        self._check_cancelled()
        self._done += 1
        self._emit()

    def cache_hit(self, path: Path) -> None:
        del path
        self._check_cancelled()
        self._cached += 1
        self._emit()

    def aggregating(self) -> None:
        self._check_cancelled()
        self._stage = "aggregating"
        self._emit(force=True)

    def reused(self, total_files: int) -> None:
        self._total = total_files
        self._cached = total_files
        self._done = 0
        self._stage = "cached"
        self._app.post_message(LoadStarted(total_files, generation=self._generation))
        self._emit(force=True)

    def finished(self) -> None:
        self._stage = "aggregating"
        self._emit(force=True)
        self._app.post_message(LoadFinished(generation=self._generation))
