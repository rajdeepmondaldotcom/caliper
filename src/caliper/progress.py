"""Optional progress callbacks for ``load_usage`` and vendor parsers.

The CLI passes ``None`` and behaves exactly as before. The Textual TUI
supplies a callback that posts thread-safe messages to the UI so the
loading overlay can show file-by-file progress.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ParseProgress(Protocol):
    """Receives progress events as ``load_usage`` and vendors parse files."""

    def starting(self, total_files: int) -> None:
        """Called once at the start of a load with the expected file count."""

    def file_done(self, path: Path) -> None:
        """Called after each file is fully parsed (cache miss path)."""

    def cache_hit(self, path: Path) -> None:
        """Called when a file was served from the parse cache."""

    def finished(self) -> None:
        """Called once after the last file."""


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


NULL_PROGRESS: ParseProgress = NullProgress()
