# Phase 3 - Plan Revision Round 1

## Revised Direction

Keep the existing parser -> aggregate -> render architecture and deepen the
interfaces already present.

No second parser, no new persistent analytics database, no prompt-content
mining, and no network dependency for normal reports.

## File-Level Plan

1. `models.py`
   - Add optional `ThreadMeta` fields for git SHA, source, thread source, CLI
     version, agent role, agent nickname, and memory mode.
   - Add aggregate provenance fields:
     `session_ids`, `project_paths`, `project_names`, `git_origins`,
     `git_branches`, `git_shas`, `agent_roles`, `sources`, `first_seen`, and
     `last_seen`.
   - Populate them in `Aggregate.add_event()`.

2. `parser.py`
   - Increment parser cache version.
   - Extend state DB loading through existing dynamic column helpers.
   - Preserve `turn_context.cwd` in event-scoped `ThreadMeta`.

3. `parse_cache.py`
   - Filter decoded `ThreadMeta` fields to known dataclass fields.

4. `aggregation.py`
   - Keep existing group keys stable.
   - Add small project helper functions for unknown-project fallback and
     project name extraction.

5. `render.py`
   - Add provenance fields to JSON aggregate objects.
   - Add top-level `projects` to JSON report payloads.
   - Add `metadata.workspace_coverage`.
   - Add normalized subscription-plan payloads and subscription warnings.
   - Include limit bucket identifiers in limits output.
   - Keep table, CSV, and Markdown unchanged.

6. `windows.py`
   - Preserve existing `compute_window_state()` semantics by defaulting to the
     main `codex` limit bucket when it exists.
   - Allow callers to request a different bucket by `limit_id`.

7. New `subscriptions.py`
   - Normalize known plan strings.
   - Keep raw plan strings in output.
   - Warn for unknown plans, promotional Free/Go access, and
     Enterprise-family legacy-rate-card ambiguity.

8. New `statusline.py`
   - Build a plain snapshot from `LoadResult`, `RuntimeOptions`, and `RateCard`.
   - Render text and JSON without importing Rich.

9. `cli.py`
   - Add the `statusline` command.
   - Preserve existing options and output conventions.
   - Keep exact amount fields in compare, what-if, and budgets JSON.

10. `README.md`
   - Add `statusline` to command list.
   - Document project JSON provenance and workspace attribution order.
   - Document subscription metadata and main-bucket window behavior.

11. Tests
   - Parser fallback from `turn_context.cwd`.
   - Optional state DB metadata.
   - Aggregate provenance.
   - JSON `projects` and workspace coverage.
   - Parse-cache tolerance for extra thread keys.
   - Limit bucket parsing and default bucket selection.
   - Subscription payloads and warnings through report JSON.
   - Statusline text and JSON.

## Commit Plan

1. Documentation roadmap.
2. Exact amount JSON fields.
3. Project provenance.
4. Statusline command.
5. README polish and audit fixes if needed.

All commit messages must be one line and must not name the benchmark project.
