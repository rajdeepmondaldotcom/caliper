from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")

MIN_PARALLEL_FILES = 16
TARGET_BATCH_BYTES = 8_000_000
MAX_BATCH_FILES = 256


def run_path_batches(
    items: Sequence[T],
    worker: Callable[..., list[R]],
    *,
    workers: int,
    size_of: Callable[[T], int] | None = None,
    worker_args: tuple = (),
    on_batch_done: Callable[[tuple[T, ...], Sequence[R]], None] | None = None,
) -> list[R]:
    """Run independent parse items in sized process-pool batches.

    Cache access stays outside this helper. The worker must be a top-level
    function so multiprocessing can import it under spawn-based platforms.
    Results are returned in deterministic batch order even though batches
    execute concurrently.
    """
    if not items:
        return []
    batches = _batches(items, size_of=size_of)
    if workers <= 1 or len(items) < MIN_PARALLEL_FILES or len(batches) <= 1:
        groups: list[list[R]] = []
        for batch in batches:
            result = worker(batch, *worker_args)
            if on_batch_done is not None:
                on_batch_done(batch, result)
            groups.append(result)
        return _flatten(groups)

    max_workers = max(1, min(int(workers), len(batches)))
    ordered: list[list[R] | None] = [None] * len(batches)
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_call_worker, worker, batch, worker_args): index
            for index, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            index = futures[future]
            result = future.result()
            ordered[index] = result
            if on_batch_done is not None:
                on_batch_done(batches[index], result)
    return _flatten(batch or [] for batch in ordered)


def path_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def assert_accounted_paths(
    expected: Sequence[Path],
    actual: Iterable[Path],
    *,
    label: str,
) -> None:
    expected_counts = Counter(str(path) for path in expected)
    actual_counts = Counter(str(path) for path in actual)
    if expected_counts == actual_counts:
        return
    missing = sorted((expected_counts - actual_counts).elements())
    extra = sorted((actual_counts - expected_counts).elements())
    details: list[str] = []
    if missing:
        details.append(f"missing {len(missing)}: {', '.join(missing[:3])}")
    if extra:
        details.append(f"unexpected {len(extra)}: {', '.join(extra[:3])}")
    raise RuntimeError(f"{label} did not account for every discovered file ({'; '.join(details)})")


def _batches(
    items: Sequence[T],
    *,
    size_of: Callable[[T], int] | None,
) -> list[tuple[T, ...]]:
    batches: list[tuple[T, ...]] = []
    current: list[T] = []
    current_bytes = 0
    for item in items:
        item_bytes = max(0, size_of(item) if size_of is not None else 0)
        if current and (
            current_bytes + item_bytes > TARGET_BATCH_BYTES or len(current) >= MAX_BATCH_FILES
        ):
            batches.append(tuple(current))
            current = []
            current_bytes = 0
        current.append(item)
        current_bytes += item_bytes
    if current:
        batches.append(tuple(current))
    return batches


def _flatten(groups: Iterable[Sequence[R]]) -> list[R]:
    out: list[R] = []
    for group in groups:
        out.extend(group)
    return out


def _call_worker(
    worker: Callable[..., list[R]],
    batch: tuple[T, ...],
    worker_args: tuple,
) -> list[R]:
    return worker(batch, *worker_args)
