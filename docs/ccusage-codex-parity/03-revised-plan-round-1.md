# Phase 3 - Plan Revision Round 1

## Revised Direction

Keep the Phase 1 architecture and tighten the data-model details from the
self-audit.

The implementation should be a focused compatibility and explainability layer:

1. honor `CODEX_HOME` for default Codex paths;
2. make model inference visible;
3. expose row-level model/tier breakdowns in JSON.

No report command should change its table, CSV, or Markdown columns.

## File-Level Plan

### `config.py`

- Replace static `DEFAULT_SESSION_ROOT`, `DEFAULT_STATE_DB`, and
  `DEFAULT_CODEX_CONFIG` path constants with helper-backed defaults.
- Add:
  - `default_codex_home()`
  - `default_session_root()`
  - `default_state_db()`
  - `default_codex_config()`
- Keep CLI path overrides first and config file values second.

### `models.py`

- Add to `UsageEvent`:
  - `model_source: str = ""`
  - `model_is_fallback: bool = False`
- Add `ModelBreakdown` with:
  - model, service tier, totals, costs, cache savings;
  - plan types, usage sources, model sources;
  - long-context, unknown-model, unknown-tier, fallback counts;
  - first/last seen.
- Add to `Aggregate`:
  - `model_sources`
  - `fallback_model_events`
  - `model_breakdowns`
- Update `Aggregate.add_event()` to populate those fields.

### `parser.py`

- Increment `PARSER_CACHE_VERSION`.
- Add model-source resolution:
  1. event-scoped `current_meta.model` from `turn_context`;
  2. original SQLite `thread_meta.model`;
  3. `options.default_model`.
- Emit source labels: `turn_context`, `state-db`, `default`.
- Mark default-model use as fallback.

### `parse_cache.py`

- Filter decoded event fields to known `UsageEvent` dataclass fields.
- Keep missing new fields backward-compatible through dataclass defaults.

### `render.py`

- Add model-source and fallback fields to `aggregate_to_dict()`.
- Add `model_breakdowns` list to each aggregate payload.
- Add exact decimal string companions for breakdown costs.
- Keep existing payload fields unchanged.

### Tests

- `test_config.py`: `CODEX_HOME` default paths.
- `test_parser.py`: model source/fallback precedence.
- `test_aggregation.py`: model breakdowns and fallback counts.
- `test_formats.py`: JSON row `model_breakdowns`.
- `test_parse_cache.py`: future event keys ignored.

### README

- Add `CODEX_HOME` to data-source documentation.
- Add a short JSON-output note for per-row model breakdowns and fallback model
  visibility.

## Acceptance Criteria

- Existing command names and formats still work.
- `CODEX_HOME=/tmp/codex-home codex-meter doctor --format json` reports default
  paths under `/tmp/codex-home` unless overridden.
- Legacy/no-model sessions appear with `model_source=default` and
  `model_is_fallback=true`.
- Daily/monthly/session/project JSON rows contain `model_breakdowns`.
- All tests and lint pass.

