# Phase 1 - Initial Implementation Plan

## Goal

Make `codex-meter` project tracking materially more granular without turning the
tool into a prompt/content miner. The user-facing outcome is:

- every usage event carries the best local workspace identity available;
- every aggregate can explain which sessions, paths, git refs, models, tiers,
  cache behavior, and time span contributed to it;
- JSON reports expose a project-by-project inventory even when the primary
  command groups by day, week, month, session, or model;
- existing table, CSV, Markdown, and command behavior remain stable unless the
  command is explicitly emitting richer JSON.

## Current Codebase Grounding

The current pipeline is already well-shaped for this work:

- `config.py` resolves local Codex data paths and runtime options.
- `parser.py` reads `~/.codex/sessions/**/*.jsonl`, joins
  `~/.codex/state_5.sqlite`, infers model/tier context, extracts token counts
  and rate-limit samples, and returns `LoadResult`.
- `models.py` defines `ThreadMeta`, `UsageEvent`, `Aggregate`, and `LoadResult`.
- `aggregation.py` groups `UsageEvent` records by day, week, month, session,
  project, and model/tier.
- `render.py` converts aggregates into table, JSON, CSV, and Markdown payloads.
- `cli.py` wires public commands; `project` currently groups by `thread.cwd`,
  and `tail` already exposes a recent-event project column.
- `parse_cache.py` serializes parsed `UsageEvent` records, so parser/data-model
  changes must invalidate cache signatures safely.

The project grouping exists, but it only uses a label. The aggregate rows do not
retain session sets, project path sets, git refs, first/last seen timestamps, or
workspace coverage metadata.

## Local Data Analysis

I scanned the local Codex session corpus structurally, without printing prompt
contents.

- 103 JSONL session files under `~/.codex/sessions`.
- 89,533 JSONL lines parsed with 0 JSON errors at scan time.
- Top event types: `response_item`, `event_msg`, `turn_context`,
  `session_meta`, and `compacted`.
- Token events are `event_msg` records with `payload.type == "token_count"`.
- `token_count` payloads contain `info.total_token_usage`,
  `info.last_token_usage`, `info.model_context_window`, and `rate_limits`.
- `rate_limits` consistently contains `limit_id`, `limit_name`, `primary`,
  `secondary`, `credits`, `plan_type`, and `rate_limit_reached_type`.
- Every scanned session had `turn_context.cwd`, token counts, and rate-limit
  samples.
- The state DB `threads` table had 103 rows, 7 distinct `cwd` values, 6
  distinct git origins, and git origin/branch/sha coverage for nearly every
  session.
- `turn_context.cwd` matched state DB `cwd` for all scanned sessions.
- `exec_command_end.cwd` had 13 distinct values, which suggests command-level
  subdirectory activity exists but should not be conflated with token-event
  workspace attribution unless explicitly modeled later.

Useful source fields:

- JSONL `turn_context`: `cwd`, `current_date`, `timezone`, `approval_policy`,
  `sandbox_policy`, `model`, `effort`, `collaboration_mode.settings`.
- SQLite `threads`: `rollout_path`, `cwd`, `git_branch`, `git_origin_url`,
  `git_sha`, `model`, `reasoning_effort`, `source`, `thread_source`,
  `cli_version`, `agent_role`, `agent_nickname`, `memory_mode`, timestamps.
- Token events: usage deltas/totals, model context window, service tier, plan
  type, credits, primary/secondary window percentages and resets.

## Architecture Decision

Keep the existing parser -> aggregate -> render architecture. Enrich it at the
data model boundary instead of adding a second analytics pipeline.

Implementation shape:

1. Enrich `ThreadMeta`.
   - Add optional fields for git SHA, source, provider/source metadata, CLI
     version, agent role/nickname, memory mode, and thread source.
   - Continue tolerating older state DB schemas through dynamic column checks.

2. Use JSONL `turn_context.cwd` as event-scoped workspace evidence.
   - `update_context_from_event()` should update `ThreadMeta.cwd` when
     `turn_context` provides a workspace.
   - State DB remains the initial session-level seed.
   - This gives correct behavior when state DB is missing or stale.

3. Preserve richer aggregate provenance.
   - Extend `Aggregate` with session IDs, project paths, project names, git
     origins, branches, SHAs, agent roles, source values, and first/last seen
     timestamps.
   - Populate these sets in `Aggregate.add_event()`.

4. Make project identity explicit in aggregation.
   - Keep grouping by local `cwd` for compatibility.
   - Use stable fallback labels when workspace path is missing.
   - Keep table labels shortened through the existing `short_table_label()`
     rendering path.

5. Enrich JSON output.
   - Add aggregate-level fields such as `session_count`, `sessions`,
     `project_paths`, `project_names`, `git_origins`, `git_branches`,
     `git_shas`, `first_seen`, and `last_seen`.
   - Add a top-level `projects` array to JSON reports so all reports include
     project-by-project detail, even if the command is `daily`, `models`, or
     `session`.
   - Add `metadata.workspace_coverage` for event/session coverage.

6. Keep non-JSON formats stable.
   - Do not widen default tables.
   - Do not add CSV columns to existing grouped exports in this pass; existing
     CSV tests pin those fields.
   - Markdown remains compact.

7. Update tests.
   - Parser tests for turn-context workspace fallback when state DB is missing.
   - State DB metadata tests for optional git/source fields.
   - Aggregation tests for session/project/git/time provenance.
   - Format tests for JSON `projects` and workspace coverage.
   - Parse cache tests for backward-compatible decode.

8. Invalidate parser cache.
   - Increment `PARSER_CACHE_VERSION` because parsed event metadata changes.
   - Make parse-cache thread decoding tolerate older payloads and future extra
     keys.

## Edge Cases

- Missing state DB: JSONL `turn_context.cwd` should still produce project
  attribution.
- Missing `turn_context.cwd`: fall back to state DB `cwd`, then `Unknown
  Project`.
- Older state DB schemas: missing optional columns must not fail loading.
- Multiple workspaces in one session: no scanned sessions had this, but the
  event-scoped `ThreadMeta` update allows future sessions to attribute token
  events to the current workspace at event time.
- Prompt privacy: do not parse message content for project identity.
- Git privacy: JSON exports may include local path and remote URL metadata; keep
  default table rendering path-redacted/shortened where it already is.
- Cache compatibility: older cached payloads should not crash; changed parser
  signatures should naturally miss and rebuild.

## Acceptance Criteria

- `codex-meter project --format json` exposes enriched project metadata.
- `codex-meter daily --format json` includes a top-level `projects` inventory.
- Existing table output remains readable and does not leak full project paths in
  the existing shortened table cases.
- Missing state DB still allows workspace tracking when JSONL turn context is
  present.
- Tests cover parser fallback, aggregate provenance, JSON payloads, and cache
  compatibility.
- All commits stay local and no Terraform commands are run.
