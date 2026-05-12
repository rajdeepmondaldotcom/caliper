# Phase 7 - Implementation Log

## Implemented

### Documentation Roadmap

- Removed the `docs/` ignore rule so implementation records can be tracked.
- Added Phase 1-6 planning, audit, and research documents.
- Kept the plan anchored to the existing parser -> aggregate -> render
  architecture.

### Exact JSON Amounts

- Preserved existing numeric JSON fields.
- Added exact decimal string companions for compare, what-if, budget, aggregate,
  and statusline amounts where Decimal-backed values are emitted.

### Project Provenance

- `ThreadMeta` carries optional git/source/agent metadata from Codex state.
- `turn_context.cwd` updates event-scoped workspace metadata.
- Aggregates retain sessions, project paths/names, git origins/branches/SHAs,
  source markers, first seen, and last seen timestamps.
- JSON reports include a top-level `projects` inventory and
  `metadata.workspace_coverage`.

### Subscription and Limit Metadata

- `UsageEvent` and `RateLimitSample` retain `limit_id` and `limit_name`.
- Limits reports expose limit bucket identifiers.
- Window math prefers the main `codex` bucket while preserving all raw samples.
- `subscriptions.py` normalizes known plan strings and emits warnings for
  unknown, promotional, and Enterprise-family ambiguity.
- Report JSON includes subscription plan payloads and warnings.

### Statusline

- Added `src/codex_meter/statusline.py`.
- Added `codex-meter statusline --format text|json`.
- Text output is one line for prompts/hooks.
- JSON output includes latest event, top project, today totals, trailing 7-day
  totals, cache ratio, rate-limit windows, pricing status, and subscription
  metadata.

### Documentation and Tests

- README documents statusline, project JSON inventory, workspace attribution,
  subscription warnings, and limit-bucket behavior.
- Tests cover parser metadata, project provenance, JSON report shape, limits
  output, subscription normalization, main-bucket window selection, and
  statusline text/JSON.

## Verification

- `uv run ruff check .`: passed.
- `uv run pytest`: 187 passed.
- `git diff --check`: passed.
- `uv run codex-meter statusline --format json --days 1 --no-parse-cache`:
  passed.
- `uv run codex-meter daily --format json --days 1 --no-parse-cache`: passed.

## Constraints

- No push performed.
- No Terraform commands run.
