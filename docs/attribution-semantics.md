# Caliper Attribution Semantics

Caliper attribution is intentionally conservative.

- Exact commit attribution uses a recorded `git_sha` on a usage event.
- PR attribution resolves commits from `gh pr view`, then local
  `.git/refs/pull/<N>/head`, then fails with a hint.
- Range attribution uses `git log A...B`.
- Rebases and cherry-picks are grouped by a stable hash of
  `(author_date, normalized_subject)`.
- Squash merges collapse into the squash commit when that commit is the only
  locally visible commit.
- Events without a matching commit stay in the `unattributed` bucket.
