"""Optional progress callbacks for ``load_usage``, vendor parsers, and the
multi-stage report pipeline.

The CLI passes ``None`` and behaves exactly as before. The Textual TUI
supplies a callback that posts thread-safe messages to the UI so the
loading overlay can show file-by-file progress.

Phase A widens the Protocol to include three stage events
(``stage_start``, ``stage_advance``, ``stage_done``) so the CLI can
surface aggregation/insights/render progress beyond the parse step.
Existing implementations (TUI's ``TextualParseProgress``,
``CliParseProgress``) keep working — the new methods have no-op
defaults on ``NullProgress`` and consumers that don't supply them are
treated as parse-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ParseProgress(Protocol):
    """Receives progress events as ``load_usage``, vendors, aggregators,
    and renderers do their work."""

    # ---- Parse-phase callbacks (back-compat) ------------------------------
    def starting(self, total_files: int) -> None:
        """Called once at the start of a load with the expected file count."""

    def file_done(self, path: Path) -> None:
        """Called after each file is fully parsed (cache miss path)."""

    def cache_hit(self, path: Path) -> None:
        """Called when a file was served from the parse cache."""

    def finished(self) -> None:
        """Called once after the last file."""

    def file_progress(self, path: Path, bytes_read: int, total_bytes: int) -> None:
        """Called while a large file is being parsed, before ``file_done``."""

    def usage_footprint(
        self,
        *,
        total_files: int,
        total_bytes: int,
        vendor_summary: str,
        window_label: str,
        unreadable_files: int = 0,
    ) -> None:
        """Called after discovery so the CLI can set scan-size expectations."""

    # ---- Stage callbacks (multi-stage report progress) --------------------
    def stage_start(self, name: str, total: int | None = None) -> None:
        """Called at the beginning of a named stage (``parse``, ``aggregate``,
        ``analyse``, ``render``, ``write``). ``total`` is the expected unit
        count when known, ``None`` for indeterminate stages."""

    def stage_advance(self, n: int = 1, detail: str | None = None) -> None:
        """Advance the current stage by ``n`` units. ``detail`` is a short
        human-readable label shown next to the progress bar."""

    def stage_done(self, name: str, summary: str | None = None) -> None:
        """Mark a stage as completed. ``summary`` is shown alongside the
        finished bar (e.g. ``"3 files (cached 1)"``)."""


class NullProgress:
    """No-op implementation used as the default."""

    def starting(self, total_files: int) -> None:
        return None

    def file_done(self, path: Path) -> None:
        return None

    def cache_hit(self, path: Path) -> None:
        return None

    def finished(self) -> None:
        return None

    def file_progress(self, path: Path, bytes_read: int, total_bytes: int) -> None:
        return None

    def usage_footprint(
        self,
        *,
        total_files: int,
        total_bytes: int,
        vendor_summary: str,
        window_label: str,
        unreadable_files: int = 0,
    ) -> None:
        return None

    def stage_start(self, name: str, total: int | None = None) -> None:
        return None

    def stage_advance(self, n: int = 1, detail: str | None = None) -> None:
        return None

    def stage_done(self, name: str, summary: str | None = None) -> None:
        return None


NULL_PROGRESS: ParseProgress = NullProgress()


def report_file_progress(
    progress: object,
    path: Path,
    bytes_read: int,
    total_bytes: int,
) -> None:
    """Best-effort byte progress for implementations that support it.

    Older ``ParseProgress`` stand-ins used by tests and integrations do
    not implement ``file_progress``. Keep this as an optional callback so
    parser instrumentation does not break those callers.
    """
    callback = getattr(progress, "file_progress", None)
    if callback is None:
        return
    callback(path, bytes_read, total_bytes)
