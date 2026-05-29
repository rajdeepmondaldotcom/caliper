"""Local-git commit counting for the "what this produced" view.

`discover_repo_roots` resolves the unique repositories a set of working dirs
belongs to (skipping non-repos), and `count_commits_in_window` counts the
commits authored inside a time window across those repos, reading only local
`git log`. Together they answer "how many commits shipped in this window?"
truthfully, for every source, not just the ones that log a checked-out SHA.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess  # nosec
from pathlib import Path

from caliper.git import count_commits_in_window, discover_repo_roots


def _run(repo: Path, *args: str, when: dt.datetime | None = None) -> None:
    env = dict(os.environ)
    if when is not None:
        iso = when.isoformat()
        env.update(
            GIT_AUTHOR_DATE=iso,
            GIT_COMMITTER_DATE=iso,
            GIT_AUTHOR_NAME="Tester",
            GIT_AUTHOR_EMAIL="tester@example.com",
            GIT_COMMITTER_NAME="Tester",
            GIT_COMMITTER_EMAIL="tester@example.com",
        )
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)  # noqa: S603,S607


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "tester@example.com")
    _run(repo, "config", "user.name", "Tester")


def _commit(repo: Path, name: str, when: dt.datetime) -> None:
    (repo / name).write_text("x", encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", name, when=when)


def test_count_commits_in_window_counts_only_in_range(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    base = dt.datetime(2026, 5, 15, 12, tzinfo=dt.UTC)
    # Commit dates increase along history, as in real repos. The first commit
    # predates the window and must not be counted.
    _commit(repo, "old.txt", base - dt.timedelta(days=40))
    for i in range(3):
        _commit(repo, f"in-{i}.txt", base + dt.timedelta(days=i))

    roots = discover_repo_roots([str(repo)])
    assert len(roots) == 1

    count = count_commits_in_window(roots, base - dt.timedelta(days=1), base + dt.timedelta(days=5))
    assert count == 3


def test_discover_repo_roots_dedupes_and_skips_non_repos(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    not_a_repo = tmp_path / "loose"
    not_a_repo.mkdir()
    sub = repo / "pkg" / "src"
    sub.mkdir(parents=True)

    roots = discover_repo_roots(
        [str(repo), str(sub), str(not_a_repo), str(tmp_path / "missing"), ""]
    )
    # repo and its subdir resolve to the same single root; non-repo, missing
    # path, and empty string are skipped.
    assert len(roots) == 1


def test_count_commits_in_window_empty_for_no_repos() -> None:
    now = dt.datetime(2026, 5, 15, 12, tzinfo=dt.UTC)
    assert count_commits_in_window([], now - dt.timedelta(days=1), now) == 0
