from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

from caliper.git import commit_for_sha, commit_message_hash, commits_for_revspec


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "file.txt").write_text("one\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "First change")
    (repo / "file.txt").write_text("two\n")
    _git(repo, "commit", "-am", "Second change")
    return repo


def test_commit_message_hash_is_stable_for_same_subject_and_date() -> None:
    date = dt.datetime(2026, 5, 12, tzinfo=dt.UTC)

    assert commit_message_hash(date, "  Add   thing ") == commit_message_hash(date, "add thing")


def test_git_log_reads_range_commit_metadata(tmp_path) -> None:
    repo = _repo(tmp_path)
    commits = commits_for_revspec("HEAD~1..HEAD", repo)

    assert len(commits) == 1
    assert commits[0].subject == "Second change"
    assert commits[0].sha


def test_commit_for_sha_reads_single_commit(tmp_path) -> None:
    repo = _repo(tmp_path)
    sha = _git(repo, "rev-parse", "HEAD")

    commit = commit_for_sha(sha, repo)

    assert commit.sha == sha
    assert commit.subject == "Second change"
