from __future__ import annotations

from pathlib import Path

import pytest

from caliper import parse_parallel


def _double_batch(batch: tuple[int, ...]) -> list[int]:
    return [item * 2 for item in batch]


def test_run_path_batches_uses_process_pool_and_preserves_order(monkeypatch) -> None:
    monkeypatch.setattr(parse_parallel, "MIN_PARALLEL_FILES", 2)
    monkeypatch.setattr(parse_parallel, "MAX_BATCH_FILES", 1)

    result = parse_parallel.run_path_batches(
        [1, 2, 3, 4],
        _double_batch,
        workers=2,
    )

    assert result == [2, 4, 6, 8]


def test_run_path_batches_worker_count_one_is_sequential(monkeypatch) -> None:
    monkeypatch.setattr(parse_parallel, "MIN_PARALLEL_FILES", 2)
    monkeypatch.setattr(parse_parallel, "MAX_BATCH_FILES", 1)

    result = parse_parallel.run_path_batches(
        [1, 2, 3, 4],
        _double_batch,
        workers=1,
    )

    assert result == [2, 4, 6, 8]


def test_run_path_batches_reports_completed_batches(monkeypatch) -> None:
    monkeypatch.setattr(parse_parallel, "MIN_PARALLEL_FILES", 2)
    monkeypatch.setattr(parse_parallel, "MAX_BATCH_FILES", 1)
    completed: list[tuple[int, ...]] = []

    result = parse_parallel.run_path_batches(
        [1, 2, 3, 4],
        _double_batch,
        workers=2,
        on_batch_done=lambda batch, _result: completed.append(batch),
    )

    assert result == [2, 4, 6, 8]
    assert sorted(completed) == [(1,), (2,), (3,), (4,)]


def test_assert_accounted_paths_rejects_missing_or_extra_paths() -> None:
    expected = [Path("/tmp/a.jsonl"), Path("/tmp/b.jsonl")]

    with pytest.raises(RuntimeError, match="missing 1"):
        parse_parallel.assert_accounted_paths(
            expected,
            [Path("/tmp/a.jsonl")],
            label="test parser",
        )

    with pytest.raises(RuntimeError, match="unexpected 1"):
        parse_parallel.assert_accounted_paths(
            expected,
            [Path("/tmp/a.jsonl"), Path("/tmp/b.jsonl"), Path("/tmp/c.jsonl")],
            label="test parser",
        )
