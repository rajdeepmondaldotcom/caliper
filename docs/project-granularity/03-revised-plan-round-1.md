# Phase 3 - Revised Plan Round 1

## Revisions From Self-Audit

The core architecture remains unchanged: enrich parsed events, preserve
aggregate provenance, and expose project detail in JSON.

The revised implementation adds these specifics:

1. Add project helper functions.
   - `project_path_for_event(event)` returns `event.thread.cwd` or a stable
     unknown label.
   - `project_name_from_path(path)` returns the final path component or
     `Unknown Project`.
   - Keep this logic in `aggregation.py` unless it grows enough to justify a
     new module.

2. Enrich `ThreadMeta` carefully.
   - Add defaults only.
   - Extend dynamic SQLite column loading in `load_thread_metadata()`.
   - Keep schema tolerance for historical `threads` tables.

3. Update parser context handling.
   - On `turn_context`, update `cwd` if present.
   - Do not read prompt/message payloads for project inference.
   - Keep service-tier behavior unchanged.

4. Extend `Aggregate`.
   - Add:
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
   - Populate these in `add_event()`.

5. Enrich JSON only.
   - `aggregate_to_dict()` emits the new fields.
   - `report_payload()` adds:
     - `projects`: all project aggregates for the selected window;
     - `metadata.workspace_coverage`: event/session coverage counts.
   - Table, CSV, and Markdown formats keep their current columns.

6. Harden parse cache.
   - Increment `PARSER_CACHE_VERSION`.
   - Filter unknown `ThreadMeta` keys during cache decode.

7. Documentation.
   - README gets a short note under Data Sources or Accuracy explaining
     workspace attribution order:
     1. JSONL `turn_context.cwd`
     2. SQLite `threads.cwd`
     3. unknown project fallback
   - Mention JSON project inventories.

8. Tests.
   - Parser:
     - missing state DB still gets `cwd` from `turn_context`;
     - extended state DB fields load when present.
   - Aggregation:
     - project provenance fields populate and first/last seen are tracked.
   - Format:
     - top-level JSON includes `projects`;
     - workspace coverage is present;
     - CSV fields remain unchanged.
   - Parse cache:
     - cached thread dict with unknown keys decodes instead of failing.

## Non-Goals

- No command-level activity mining from `exec_command_end.cwd`.
- No prompt content analysis.
- No new persistent database.
- No network dependency.
- No Terraform commands.
