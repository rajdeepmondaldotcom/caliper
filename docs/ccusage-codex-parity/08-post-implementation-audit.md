# Phase 8 - Post-Implementation Audit

## Audit Basis

Audited implementation against:

- `docs/ccusage-codex-parity/06-final-implementation-plan.md`
- `src/codex_meter/config.py`
- `src/codex_meter/models.py`
- `src/codex_meter/parser.py`
- `src/codex_meter/parse_cache.py`
- `src/codex_meter/render.py`
- `README.md`
- related tests and smoke outputs

## Findings

### Finding 1 - `CODEX_HOME` support matches the plan

Status: pass.

`config.py` now resolves default Codex paths through `default_codex_home()`.
Tests cover non-empty `CODEX_HOME` and whitespace-only `CODEX_HOME`. Explicit
CLI/config path precedence remains unchanged.

### Finding 2 - Model-source and fallback metadata match the plan

Status: pass.

`UsageEvent` now records `model_source` and `model_is_fallback`. Parser source
precedence is implemented as:

1. `turn_context`;
2. `state-db`;
3. `default`.

Tests cover all three source paths.

### Finding 3 - Parser cache compatibility matches the plan

Status: pass.

`PARSER_CACHE_VERSION` was incremented to invalidate old parsed payloads, and
parse-cache event decoding now filters unknown future keys.

### Finding 4 - Row-level model breakdowns match the plan

Status: pass.

`Aggregate` now tracks `model_sources`, `fallback_model_events`, and
`model_breakdowns`. Each model breakdown retains token totals, costs, cache
savings, pricing flags, first/last timestamps, sources, and fallback counts.

### Finding 5 - JSON output is enriched without changing other formats

Status: pass.

`render.py` adds JSON-only fields to aggregate payloads. Table, CSV, and
Markdown rendering paths were not changed. Existing format tests still pass.

### Finding 6 - README matches the implemented behavior

Status: pass.

README now documents `CODEX_HOME`, row-level JSON `model_breakdowns`, and model
source/fallback visibility.

### Finding 7 - Verification matches the final plan

Status: pass.

Full tests, lint, diff whitespace checks, and focused CLI smokes passed. The
`CODEX_HOME` smoke intentionally exited `2` because the chosen directory was
missing, and the JSON payload confirmed path resolution under that environment
home.

## Deviations

No code deviations requiring fixes were found.

One deliberate refinement: fallback model events now contribute to
`pricing_status == "estimated"`. This is stricter than the Phase 1 wording and
matches the goal of making assumptions visible instead of treating configured
default-model pricing as observed model metadata.

## Audit Result

No Phase 8 findings require code fixes.

