# Phase 6 - Final Consolidated Implementation Plan

## Summary

Implement two user-visible improvements grounded in the current codebase:

1. richer project/workspace provenance in JSON reports;
2. subscription and rate-limit bucket explainability;
3. a compact `statusline` command for quick local usage snapshots.

Also preserve exact Decimal-backed amounts in JSON outputs where float fields are
kept for compatibility.

## Implementation Steps

1. Repository docs
   - Track `docs/` by removing the ignore rule.
   - Replace stale phase documents with this implementation record.

2. Exact JSON amounts
   - Keep existing numeric fields.
   - Add `credits_exact`, `api_dollars_exact`, and related exact fields in
     compare, what-if, and budget JSON outputs.

3. Project provenance
   - Extend `ThreadMeta` and `Aggregate`.
   - Read optional state DB fields if available.
   - Update event-scoped workspace from `turn_context.cwd`.
   - Harden parse-cache thread decoding.
   - Increment parser cache version.
   - Add `projects` and `workspace_coverage` to JSON payloads.

4. Statusline
   - Add `src/codex_meter/statusline.py`.
   - Add `codex-meter statusline --format text|json`.
   - Reuse pricing, aggregation, and window computations.

5. Subscription and limits
   - Add `src/codex_meter/subscriptions.py`.
   - Normalize known subscription plans while preserving raw `plan_type`.
   - Surface warnings for unknown, promotional, and Enterprise-family plans.
   - Preserve `limit_id` and `limit_name` on usage events and rate-limit
     samples.
   - Prefer the main `codex` bucket in default window summaries.

6. Documentation
   - Update README command table and examples.
   - Document workspace attribution order:
     `turn_context.cwd`, then `state_5.sqlite` thread metadata, then unknown
     project fallback.
   - Document subscription metadata and limit-bucket behavior.

7. Verification
   - `git diff --check`
   - `uv run ruff check .`
   - `uv run pytest`
   - targeted CLI smoke checks for `daily --format json` and `statusline`

8. Commits
   - Make logical, local commits only.
   - Use one-line professional commit messages.
   - Do not push.
   - Do not run Terraform commands.

## Non-Goals

- No full activity-block command in this pass.
- No embedded query language.
- No prompt-content parsing.
- No new network dependency.
- No Prometheus project-path labels.
