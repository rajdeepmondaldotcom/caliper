"""Custom Textual messages used by workers to update the UI safely.

``post_message`` is thread-safe; widget mutation is not. Workers post
these messages from worker threads and handlers in ``CaliperApp`` (or
individual screens) apply them on the main thread.
"""

from __future__ import annotations

from pathlib import Path

from textual.message import Message

from caliper.models import LoadResult
from caliper.pricing import RateCard


class LoadStarted(Message):
    """Emitted once at the start of a load. ``total`` is the file count."""

    def __init__(self, total: int) -> None:
        super().__init__()
        self.total = total


class LoadFileDone(Message):
    """A single file finished parsing (cache miss path)."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class LoadFileCacheHit(Message):
    """A single file was served from the parse cache."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class LoadFinished(Message):
    """Last file done; ``LoadSucceeded`` follows once aggregation is ready."""


class LoadSucceeded(Message):
    """Workers post this with the parsed result + rate card."""

    def __init__(self, result: LoadResult, rate_card: RateCard) -> None:
        super().__init__()
        self.result = result
        self.rate_card = rate_card


class LoadFailed(Message):
    """Workers post this when the load raised an unexpected exception."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error


class LoadCancelled(Message):
    """The worker observed a cancellation request mid-flight."""


class WorkerCancelled(RuntimeError):
    """Raised by ``TextualParseProgress`` callbacks to abort the parse."""
