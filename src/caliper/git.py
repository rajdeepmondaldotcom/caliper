from __future__ import annotations

import datetime as dt
import hashlib
import subprocess  # nosec
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from caliper.timeutil import parse_datetime


@dataclass(frozen=True)
class GitCommit:
    sha: str
    author_date: dt.datetime
    subject: str
    repo: Path

    @property
    def message_hash(self) -> str:
        return commit_message_hash(self.author_date, self.subject)


def commit_message_hash(author_date: dt.datetime, subject: str) -> str:
    normalized_subject = " ".join(subject.strip().lower().split())
    payload = f"{author_date.astimezone(dt.UTC).isoformat()}\0{normalized_subject}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def repo_root(path: Path | None = None) -> Path:
    cwd = path or Path.cwd()
    completed = _git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(completed.strip())


def commits_for_revspec(revspec: str, repo: Path | None = None) -> list[GitCommit]:
    root = repo_root(repo)
    output = _git(
        ["log", "--reverse", "--format=%H%x00%aI%x00%s", revspec],
        cwd=root,
    )
    commits: list[GitCommit] = []
    for line in output.splitlines():
        parts = line.split("\0", 2)
        if len(parts) != 3:
            continue
        commits.append(
            GitCommit(
                sha=parts[0],
                author_date=parse_datetime(parts[1]).astimezone(dt.UTC),
                subject=parts[2],
                repo=root,
            )
        )
    return commits


def commit_for_sha(sha: str, repo: Path | None = None) -> GitCommit:
    commits = commits_for_revspec(f"{sha}^!", repo)
    if not commits:
        raise ValueError(f"commit not found: {sha}")
    return commits[0]


def local_pull_ref(pr_number: int, repo: Path | None = None) -> str | None:
    root = repo_root(repo)
    path = root / ".git" / "refs" / "pull" / str(pr_number) / "head"
    if not path.exists():
        return None
    return path.read_text().strip() or None


def gh_pr_commit_shas(pr_number: int, repo: Path | None = None) -> list[str]:
    root = repo_root(repo)
    completed = subprocess.run(  # noqa: S603 # nosec
        ["gh", "pr", "view", str(pr_number), "--json", "commits", "--jq", ".commits[].oid"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def discover_repo_roots(cwds: Iterable[Path | str]) -> list[Path]:
    """Resolve the unique git repository roots for a set of working dirs.

    Best-effort: working dirs that no longer exist, sit outside any repo, or
    fail `git rev-parse` are silently skipped. Returns roots in first-seen
    order so callers get a stable, deduped list. Each distinct path is probed
    once even if many sessions share it.
    """
    roots: dict[str, Path] = {}
    seen_cwds: set[str] = set()
    for cwd in cwds:
        if not cwd:
            continue
        key = str(cwd)
        if key in seen_cwds:
            continue
        seen_cwds.add(key)
        try:
            root = repo_root(Path(key))
        except (ValueError, OSError):
            continue
        roots.setdefault(str(root), root)
    return list(roots.values())


def count_commits_in_window(
    repo_roots: Iterable[Path],
    start: dt.datetime,
    end: dt.datetime,
) -> int:
    """Count distinct commits authored in ``[start, end)`` across repos.

    Reads local `git log` only (no network). Commit SHAs are globally unique,
    so the union across repos deduplicates naturally. Any repo that fails
    (detached, corrupt, permission) is skipped rather than failing the whole
    count, so the figure is a floor, never an error.
    """
    start_iso = start.astimezone(dt.UTC).isoformat()
    end_iso = end.astimezone(dt.UTC).isoformat()
    shas: set[str] = set()
    for root in repo_roots:
        try:
            output = _git(
                ["log", f"--since={start_iso}", f"--until={end_iso}", "--format=%H"],
                cwd=root,
            )
        except (ValueError, OSError):
            continue
        shas.update(line.strip() for line in output.splitlines() if line.strip())
    return len(shas)


def _git(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(  # noqa: S603 # nosec
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError((completed.stderr or completed.stdout or "git command failed").strip())
    return completed.stdout
