"""Custom Textual messages used by workers to update the UI safely.

``post_message`` is thread-safe; widget mutation is not. Workers post
these messages from worker threads and handlers in ``CaliperApp`` (or
individual screens) apply them on the main thread.
"""

from __future__ import annotations

from textual.message import Message

from caliper.models import LoadResult
from caliper.pricing import RateCard


class LoadStarted(Message):
    """Emitted once at the start of a load. ``total`` is the file count."""

    def __init__(self, total: int, *, generation: int = 0) -> None:
        super().__init__()
        self.total = total
        self.generation = generation


class LoadProgress(Message):
    """Coalesced file progress for the loading overlay."""

    def __init__(
        self,
        *,
        total: int,
        done: int,
        cached: int,
        stage: str = "reading",
        generation: int = 0,
    ) -> None:
        super().__init__()
        self.total = total
        self.done = done
        self.cached = cached
        self.stage = stage
        self.generation = generation


class LoadFileDone(Message):
    """Deprecated per-file progress message kept for compatibility."""

    def __init__(self, *, generation: int = 0) -> None:
        super().__init__()
        self.generation = generation


class LoadFileCacheHit(Message):
    """Deprecated per-file cache-hit message kept for compatibility."""

    def __init__(self, *, generation: int = 0) -> None:
        super().__init__()
        self.generation = generation


class LoadFinished(Message):
    """Last file done; ``LoadSucceeded`` follows once aggregation is ready."""

    def __init__(self, *, generation: int = 0) -> None:
        super().__init__()
        self.generation = generation


class LoadSucceeded(Message):
    """Workers post this with the parsed result + rate card."""

    def __init__(
        self,
        result: LoadResult,
        rate_card: RateCard,
        derived: dict,
        manifest: object,
        *,
        reused: bool = False,
        generation: int = 0,
    ) -> None:
        super().__init__()
        self.result = result
        self.rate_card = rate_card
        self.derived = derived
        self.manifest = manifest
        self.reused = reused
        self.generation = generation


class LoadFailed(Message):
    """Workers post this when the load raised an unexpected exception."""

    def __init__(self, error: BaseException, *, generation: int = 0) -> None:
        super().__init__()
        self.error = error
        self.generation = generation


class LoadCancelled(Message):
    """The worker observed a cancellation request mid-flight."""

    def __init__(self, *, generation: int = 0) -> None:
        super().__init__()
        self.generation = generation


class WorkerCancelled(RuntimeError):
    """Raised by ``TextualParseProgress`` callbacks to abort the parse."""
