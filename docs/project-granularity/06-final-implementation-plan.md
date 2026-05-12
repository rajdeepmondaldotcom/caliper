# Phase 6 - Final Consolidated Implementation Plan

## Summary

Implement project-by-project granular tracking by enriching existing parsed
events and aggregates. Do not add a parallel analytics pipeline. Do not mine
prompt/tool content. Preserve existing table/CSV/Markdown behavior and expand
JSON reports with explicit project inventories and workspace coverage metadata.

## Implementation Tasks

### 1. Parser and data model

- Extend `ThreadMeta` with optional defaults:
  - `git_sha`
  - `source`
  - `model_provider`
  - `cli_version`
  - `agent_role`
  - `agent_nickname`
  - `memory_mode`
  - `thread_source`
- Extend `load_thread_metadata()` to read those columns when present.
- Update `update_context_from_event()` so `turn_context.cwd` refreshes the
  current event-scoped `ThreadMeta.cwd`.
- Increment `PARSER_CACHE_VERSION`.
- Harden parse-cache `ThreadMeta` decoding by filtering unknown keys.

### 2. Aggregate provenance

- Extend `Aggregate` with:
  - `session_ids`
  - `project_paths`
  - `project_names`
  - `git_origins`
  - `git_branches`
  - `git_shas`
  - `agent_roles`
  - `sources`
  - `first_seen`
  - `last_seen`
- Populate these fields in `Aggregate.add_event()`.
- Keep `aggregate_projects()` grouped by workspace path for compatibility.

### 3. JSON payloads

- Add the new provenance fields to `aggregate_to_dict()`.
- Add top-level `projects` to `report_payload()` using `aggregate_projects()`.
- Add `metadata.workspace_coverage` with event/session coverage counts.
- Keep existing table, CSV, and Markdown columns stable.

### 4. README

- Document workspace attribution order:
  1. JSONL `turn_context.cwd`
  2. SQLite `threads.cwd`
  3. `Unknown Project`
- Mention that JSON reports include a project inventory for the selected window.
- Strengthen the privacy note for local paths and git remotes.

### 5. Tests

- Parser tests:
  - `turn_context.cwd` works without state DB.
  - extended state DB metadata loads.
- Aggregation tests:
  - aggregate provenance sets and first/last seen timestamps populate.
- Format tests:
  - JSON top-level keys include `projects`.
  - `metadata.workspace_coverage` is present.
  - CSV field set remains unchanged.
- Parse cache tests:
  - unknown future `ThreadMeta` keys in cached payloads do not crash decode.

### 6. Verification

- `uv run ruff check .`
- `uv run pytest`
- Focused smoke:
  - `uv run codex-meter project --days 7 --format json`
  - `uv run codex-meter daily --days 7 --format json`

## Commit Plan

1. `docs: plan granular project tracking`
2. `feat: enrich workspace metadata parsing`
3. `feat: expose project provenance in reports`
4. `docs: document workspace-level reporting`
5. `test: cover granular project tracking`
6. Optional audit-fix commit if Phase 8 finds gaps

All commits remain local. No push. No Terraform commands.
