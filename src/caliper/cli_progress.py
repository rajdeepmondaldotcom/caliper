"""Honest progress reporting for the classic CLI report commands.

Wraps a Rich ``Progress`` widget against stderr so the user sees:

  Reading sessions  [#####------]  1,283 / 4,210  (cached: 902)
  last: rollout-2026-05-12T14-31-22-...jsonl

The widget activates only when:
  - stderr is a TTY, and
  - the user did not pass --format / --out (those are pipe paths).

Otherwise the CLI falls back to a single one-line stderr hint, matching
the previous behaviour exactly.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from caliper.progress import NULL_PROGRESS, ParseProgress


class CliParseProgress:
    """ParseProgress implementation backed by a Rich ``Progress`` widget."""

    def __init__(self, progress: Progress, task_id) -> None:
        self._progress = progress
        self._task = task_id
        self._total = 0
        self._done = 0
        self._cached = 0

    def starting(self, total_files: int) -> None:
        self._total = total_files
        self._progress.update(
            self._task,
            total=max(total_files, 1),
            description=f"Reading {total_files:,} files",
        )

    def file_done(self, path: Path) -> None:
        self._done += 1
        self._tick(path)

    def cache_hit(self, path: Path) -> None:
        self._cached += 1
        self._done += 1
        self._tick(path)

    def finished(self) -> None:
        self._progress.update(
            self._task,
            completed=max(self._done, 1),
            description=(
                f"Read {self._done:,} files"
                + (f" (cached {self._cached:,})" if self._cached else "")
            ),
        )

    def _tick(self, path: Path) -> None:
        suffix = Path(path).name
        if len(suffix) > 48:
            suffix = "..." + suffix[-45:]
        self._progress.update(
            self._task,
            completed=self._done,
            description=(
                f"Reading {self._done:,} / {self._total:,}"
                + (f"  cached {self._cached:,}" if self._cached else "")
                + f"  last: {suffix}"
            ),
        )


@contextmanager
def cli_parse_progress(
    *,
    output_format: str,
    output: Path | None,
):
    """Context manager that yields a :class:`ParseProgress` for ``load_usage``.

    Falls back to :data:`caliper.progress.NULL_PROGRESS` when the user is
    piping, writing to a file, or otherwise not in an interactive shell.
    """
    if output is not None or output_format != "table" or not sys.stderr.isatty():
        yield NULL_PROGRESS
        return

    console = Console(stderr=True)
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(bar_width=24),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
        refresh_per_second=8,
    ) as progress:
        task_id = progress.add_task("Reading sessions", total=1)
        yield CliParseProgress(progress, task_id)


__all__ = ["CliParseProgress", "cli_parse_progress"]


def _typecheck() -> None:  # pragma: no cover - structural typing sanity
    bridge: ParseProgress = CliParseProgress.__new__(CliParseProgress)
    assert bridge  # noqa: S101 - documentary
