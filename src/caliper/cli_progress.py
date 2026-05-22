"""Honest, multi-stage progress reporting for the CLI report commands.

Wraps a Rich ``Progress`` widget against stderr so the user sees:

  ⠋ Reading sessions [#####------]  1,283 / 4,210 (cached 902)
    last: rollout-2026-05-12T14-31-22-...jsonl
  ⠧ Aggregating totals · by model · by session
    ✓ done

The widget activates when:
  - ``--progress`` is passed (force on, even on non-TTY / JSON paths), OR
  - stderr is a TTY AND ``--format=table`` AND ``--out`` is unset (the
    legacy auto-detect rule).

``--quiet`` overrides every signal and yields ``NULL_PROGRESS``. Output
always goes to stderr so JSON/CSV/HTML paths on stdout stay byte-clean.
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


def _format_bytes(size: int) -> str:
    value = float(max(size, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1000 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1000
    return f"{value:.1f} GB"


class CliParseProgress:
    """Legacy single-task ParseProgress backed by a Rich ``Progress``.

    Kept for back-compat; new call sites should construct
    :class:`CliReportProgress` via :func:`cli_report_progress`.
    """

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

    # Stage methods are no-ops on the legacy widget. The multi-task class
    # below uses them; mixing both keeps `cli_parse_progress` callers safe.
    def stage_start(self, name: str, total: int | None = None) -> None:
        return None

    def stage_advance(self, n: int = 1, detail: str | None = None) -> None:
        return None

    def stage_done(self, name: str, summary: str | None = None) -> None:
        return None

    def file_progress(self, path: Path, bytes_read: int, total_bytes: int) -> None:
        del path, bytes_read, total_bytes
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
        del total_files, total_bytes, vendor_summary, window_label, unreadable_files
        return None

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


class CliReportProgress:
    """Multi-stage ParseProgress.

    One Rich ``Progress`` widget hosts one task per stage. Parse-phase
    callbacks (``starting``/``file_done``/``cache_hit``/``finished``) feed
    the currently-active ``parse`` task if one was started; otherwise they
    are no-ops so a caller that only registered ``aggregate``/``render``
    stages doesn't see phantom parse output.
    """

    def __init__(self, progress: Progress) -> None:
        self._progress = progress
        self._tasks: dict[str, object] = {}
        self._current: str | None = None
        # Parse-task bookkeeping (mirrors CliParseProgress).
        self._parse_total = 0
        self._parse_done = 0
        self._parse_cached = 0
        self._active_path: Path | None = None

    # ---- Stage events ------------------------------------------------------
    def stage_start(self, name: str, total: int | None = None) -> None:
        if name in self._tasks:
            # Stage re-entered (e.g. dashboard's two parse passes). Reset.
            self._progress.update(
                self._tasks[name],
                completed=0,
                total=total if total is not None else 1,
                description=self._describe(name),
            )
        else:
            self._tasks[name] = self._progress.add_task(
                self._describe(name),
                total=total if total is not None else 1,
            )
        self._current = name
        if name == "parse":
            self._parse_total = 0
            self._parse_done = 0
            self._parse_cached = 0
            self._active_path = None

    def stage_advance(self, n: int = 1, detail: str | None = None) -> None:
        if self._current is None or self._current not in self._tasks:
            return None
        task_id = self._tasks[self._current]
        desc = self._describe(self._current)
        if detail:
            desc = f"{desc} · {detail}"
        self._progress.update(task_id, advance=n, description=desc)

    def stage_done(self, name: str, summary: str | None = None) -> None:
        if name not in self._tasks:
            return None
        task_id = self._tasks[name]
        desc = f"✓ {self._describe(name)}"
        if summary:
            desc = f"{desc} — {summary}"
        # Snap the bar to 100% on completion.
        task = self._progress.tasks[self._task_index(task_id)]
        total = task.total if task.total else 1
        self._progress.update(task_id, completed=total, description=desc)
        if self._current == name:
            self._current = None

    # ---- Parse-phase passthroughs ------------------------------------------
    def starting(self, total_files: int) -> None:
        if "parse" not in self._tasks:
            return None
        self._parse_total = total_files
        self._progress.update(
            self._tasks["parse"],
            total=max(total_files, 1),
            description=f"Reading {total_files:,} files",
        )

    def file_done(self, path: Path) -> None:
        if "parse" not in self._tasks:
            return None
        self._parse_done += 1
        self._tick(path)

    def cache_hit(self, path: Path) -> None:
        if "parse" not in self._tasks:
            return None
        self._parse_cached += 1
        self._parse_done += 1
        self._tick(path)

    def finished(self) -> None:
        if "parse" not in self._tasks:
            return None
        self._progress.update(
            self._tasks["parse"],
            completed=max(self._parse_done, 1),
            description=(
                f"Read {self._parse_done:,} files"
                + (f" (cached {self._parse_cached:,})" if self._parse_cached else "")
            ),
        )

    def file_progress(self, path: Path, bytes_read: int, total_bytes: int) -> None:
        if "parse" not in self._tasks or total_bytes <= 0:
            return None
        self._active_path = Path(path)
        suffix = self._short_name(path)
        pct = min(100.0, max(0.0, (bytes_read / total_bytes) * 100.0))
        self._progress.update(
            self._tasks["parse"],
            completed=min(self._parse_done, max(self._parse_total, 1)),
            description=(
                f"Reading {self._parse_done:,} / {self._parse_total:,}"
                + (f"  cached {self._parse_cached:,}" if self._parse_cached else "")
                + f"  current {pct:.0f}% ({_format_bytes(bytes_read)} / "
                f"{_format_bytes(total_bytes)})  {suffix}"
            ),
        )

    def usage_footprint(
        self,
        *,
        total_files: int,
        total_bytes: int,
        vendor_summary: str,
        window_label: str,
        unreadable_files: int = 0,
    ) -> None:
        detail = (
            f"Caliper will read {total_files:,} files ({_format_bytes(total_bytes)}) "
            f"across {vendor_summary} for {window_label}."
        )
        if unreadable_files:
            detail += f" {unreadable_files:,} files could not be sized."
        if total_bytes >= 1_000_000_000 or total_files >= 1_000:
            detail += " First runs and cache rebuilds can take a few minutes."
        self._progress.console.print(detail, style="dim")

    # ---- Internals ---------------------------------------------------------
    @staticmethod
    def _describe(name: str) -> str:
        labels = {
            "discover": "Discovering data",
            "parse": "Reading sessions",
            "aggregate": "Aggregating",
            "analyse": "Analysing",
            "render": "Rendering",
            "write": "Writing",
            "build": "Building",
        }
        return labels.get(name, name.capitalize())

    def _tick(self, path: Path) -> None:
        suffix = self._short_name(path)
        self._progress.update(
            self._tasks["parse"],
            completed=self._parse_done,
            description=(
                f"Reading {self._parse_done:,} / {self._parse_total:,}"
                + (f"  cached {self._parse_cached:,}" if self._parse_cached else "")
                + f"  last: {suffix}"
            ),
        )

    @staticmethod
    def _short_name(path: Path) -> str:
        suffix = Path(path).name
        if len(suffix) > 48:
            suffix = "..." + suffix[-45:]
        return suffix

    def _task_index(self, task_id) -> int:
        for idx, task in enumerate(self._progress.tasks):
            if task.id == task_id:
                return idx
        return 0


def _should_show_progress(
    *,
    output_format: str,
    output: Path | None,
    progress: bool,
    quiet: bool,
    isatty: bool | None = None,
) -> bool:
    """Resolve the auto-detect + override matrix into one boolean.

    Rules:
      * ``quiet`` always wins → False.
      * ``progress`` forces True regardless of TTY or output shape.
      * Otherwise, legacy auto-detect: TTY stderr + table format + no ``--out``.

    ``isatty`` is the resolved stderr-TTY signal. ``None`` falls back to
    :func:`sys.stderr.isatty()`. Injecting it lets tests exercise the
    decision matrix without relying on pytest's stderr capture state.
    """
    if quiet:
        return False
    if progress:
        return True
    if output is not None or output_format != "table":
        return False
    if isatty is None:
        isatty = sys.stderr.isatty()
    return bool(isatty)


@contextmanager
def cli_parse_progress(
    *,
    output_format: str,
    output: Path | None,
):
    """Legacy single-task context manager that yields a :class:`ParseProgress`
    for ``load_usage``. Kept for callers that haven't been migrated to
    :func:`cli_report_progress` yet.
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


@contextmanager
def cli_report_progress(
    *,
    output_format: str,
    output: Path | None,
    progress: bool = False,
    quiet: bool = False,
):
    """Yield a multi-stage :class:`ParseProgress`.

    See :func:`_should_show_progress` for the activation rules. When
    inactive, ``NULL_PROGRESS`` is yielded so callers can wrap every
    long-running step in ``with cli_report_progress(...) as p`` without
    branching for the silent case.
    """
    if not _should_show_progress(
        output_format=output_format,
        output=output,
        progress=progress,
        quiet=quiet,
    ):
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
    ) as rich_progress:
        yield CliReportProgress(rich_progress)


__all__ = [
    "CliParseProgress",
    "CliReportProgress",
    "cli_parse_progress",
    "cli_report_progress",
]


def _typecheck() -> None:  # pragma: no cover - structural typing sanity
    legacy: ParseProgress = CliParseProgress.__new__(CliParseProgress)
    modern: ParseProgress = CliReportProgress.__new__(CliReportProgress)
    assert legacy and modern  # noqa: S101 - documentary
