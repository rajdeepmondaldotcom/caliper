# Phase 6 - Final Consolidated Implementation Plan

## Summary

Implement three improvements to make `codex-meter` better than
`@ccusage/codex` while preserving the current Python architecture:

1. Codex-home-aware default paths through `CODEX_HOME`;
2. model-source and fallback-model visibility;
3. row-level JSON model/tier breakdowns.

## Implementation Tasks

### 1. Configuration defaults

- Add helper functions in `config.py` for Codex home and default Codex paths.
- Use those helpers in `build_options()`.
- Add tests proving:
  - `CODEX_HOME` changes defaults;
  - explicit CLI paths still override config and environment.

### 2. Parser metadata

- Extend `UsageEvent` with `model_source` and `model_is_fallback`.
- Add a parser helper for model/source resolution.
- Use source precedence:
  1. event-scoped `turn_context` model;
  2. SQLite thread model;
  3. `default_model`.
- Mark default model use as fallback.
- Increment `PARSER_CACHE_VERSION`.
- Filter unknown `UsageEvent` keys in parse-cache decode.

### 3. Aggregate model breakdowns

- Add `ModelBreakdown` in `models.py`.
- Extend `Aggregate` with model-source/fallback counters and breakdown storage.
- Populate row-local breakdowns in `Aggregate.add_event()` using the costs
  already calculated by `aggregation.py`.

### 4. JSON rendering

- Add aggregate payload fields:
  - `model_sources`;
  - `fallback_model_events`;
  - `model_breakdowns`.
- Add exact decimal strings for breakdown amounts.
- Keep table, CSV, Markdown, and existing top-level JSON keys stable.

### 5. README

- Document `CODEX_HOME` as an environment default.
- Document model fallback/source visibility.
- Document JSON row-level `model_breakdowns`.

### 6. Verification

- `uv run ruff check .`
- `uv run pytest`
- `git diff --check`
- focused CLI smoke:
  - `uv run codex-meter daily --format json --days 1 --no-parse-cache`
  - `CODEX_HOME=/tmp/nonexistent-codex uv run codex-meter doctor --format json`

### 7. Commits

- Commit docs first.
- Commit config/parser/data-model changes next.
- Commit JSON rendering/docs/tests as a separate coherent unit if the diff is
  large enough.
- Local commits only.
- Do not push.
- Do not run Terraform commands.

## Non-Goals

- No implicit network pricing fetch.
- No locale formatting.
- No table/CSV/Markdown schema changes.
- No prompt-content mining.
- No second analytics database.

