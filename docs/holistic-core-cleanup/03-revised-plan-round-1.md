# Phase 3 - Revised Plan Round 1

## Revision Summary

The Phase 1 architecture direction stands: preserve behavior, deepen modules, and
reduce `cli.py` responsibility. Phase 2 tightened the implementation details so
the plan can be executed safely against the current code.

This revision is the working plan until industry research refines it.

## Source-of-Truth Decisions

1. No feature additions.
2. Preserve all public CLI names, flags, output formats, schemas, and exit codes.
3. Keep normal operation offline.
4. Keep Typer command functions in `cli.py`.
5. Move command support logic into pure modules with small interfaces.
6. Add tests before or alongside each extraction.
7. Do not overwrite previous root-level phase docs.

## Revised Module Plan

### `models.py`

Add:

- `ParsedSessionRecord`

Purpose:

- Named parser/cache record with fields:
  - `event: UsageEvent | None`
  - `counter_reset: bool`
  - `sample: RateLimitSample | None`

Reason:

- Avoid parser/cache circular imports.
- Replace anonymous tuples with a deeper interface.

### `parse_cache.py`

Change:

- Encode and decode `ParsedSessionRecord`.
- Preserve JSON payload keys: `event`, `reset`, `sample`.
- Continue returning `None` for unreadable or incompatible cache payloads.

Tests:

- Existing cache round-trip tests.
- Add or update assertions that decoded records expose named fields.

### `parser.py`

Change:

- Yield `ParsedSessionRecord`.
- Replace tuple unpacking in `load_usage`.
- Introduce a private rate-limit normalization helper.
- Use that helper for both `RateLimitSample` and `UsageEvent`.

Tests:

- Existing parser tests for rate-limit-only events, model-specific buckets, and
  normal usage events must keep passing.
- Add one focused assertion that a usage event and its sample preserve identical
  rate-limit fields.

### `output.py`

Add:

- `json_dumps`
- `json_default`
- `amount_fields`
- `records_to_csv`
- `records_to_markdown`

Reason:

- These are generic serialization helpers, not CLI routing.

Tests:

- Move current `tests/test_cli_helpers.py` coverage for record helpers to this
  module.

### `rate_audit.py`

Add:

- `fetched_rates_path`
- `fetch_rate_sources`
- `extract_models_from_text`
- `extract_models_from_html`
- `normal_text`
- `window_for_model`
- `extract_api_rates`
- `extract_credit_rates`
- `extract_fast_multiplier`
- `extract_long_context_rule`
- `dedupe_models`
- `rates_payload`
- `embedded_rate_snapshot`
- `rate_discrepancies`

Reason:

- This is an explicit network/audit adapter for source pages and should not live
  in the command router.

Security refinement:

- Validate that pricing source URLs use `http` or `https` before calling
  `urlopen`.
- Keep the network path behind `rates refresh --allow-network`.

Tests:

- Move network-error, JSON extraction, HTML extraction, dedupe, and refresh tests
  to the new interface where possible.

### `health.py`

Add:

- `HealthCheck`
- `check_python_version`
- `check_codex_cli_version`
- `check_clock_skew`
- `check_rate_card_age`
- `check_state_db_readable`
- `check_rates_file`
- `build_health_report`
- `worst_health_status`

Reason:

- Doctor checks are domain health logic. The CLI should render the report and
  raise the severity exit code.

Tests:

- Move direct helper tests for state DB and rates file checks out of `cli.py`.
- Keep CLI smoke tests for table, JSON, Markdown, bad format, and exit behavior.

### `scenarios.py`

Add:

- `IntervalSummary`
- `ScenarioDelta`
- `CompareResult`
- `WhatIfResult`
- pure helpers for:
  - interval aggregation;
  - Decimal-safe delta calculation;
  - compare payload construction;
  - what-if actual/projected/delta calculation;
  - no-op detection.

Reason:

- Compare and what-if are core analytical behavior with long command bodies.
  Their calculations should be testable without Typer.

Tests:

- Keep CLI tests that assert JSON and human output behavior.
- Add direct pure tests for balanced deltas, sparse warnings, no-op detection,
  unknown model/tier validation as appropriate.

### `prom_snapshot.py`

Add:

- `build_prometheus_snapshot(options: RuntimeOptions)`.

Reason:

- Prometheus metric construction is not CLI routing and already feeds the
  `prom_export.py` interface.

Tests:

- Move current `_build_prometheus_snapshot` test from `cli.py` private helper to
  this module.

### `models.Aggregate`

Change:

- Keep `add_event()` public.
- Extract private methods for:
  - totals and cost counters;
  - project/source attribution;
  - first/last seen;
  - model breakdown mutation.

Reason:

- Reduce local complexity without moving aggregate invariants away from the data
  structure.

Tests:

- Existing aggregation and JSON format tests should cover behavior.

## Revised Implementation Order

1. Add tracked domain docs and this phase document set.
2. Extract `output.py` and update tests/imports.
3. Extract `rate_audit.py` and update rates refresh/tests.
4. Extract `health.py` and update doctor/tests.
5. Extract `prom_snapshot.py` and update Prometheus tests.
6. Extract `scenarios.py` for compare and what-if calculations.
7. Add `ParsedSessionRecord` and update parser/cache.
8. Centralize rate-limit normalization.
9. Refactor `Aggregate.add_event` internally.
10. Run full verification.
11. Add quality gates only when they support the cleaned code:
    - coverage floor at or below current stable coverage;
    - optional Bandit configuration with targeted suppressions;
    - defer hard mypy until Decimal typing has a focused pass.

## Revised Acceptance Criteria

- `cli.py` loses rate-audit, health-check, Prometheus snapshot, generic output,
  and pure scenario calculation responsibilities.
- Tests import extracted helpers from their real modules instead of private CLI
  helpers.
- Parser/cache records use named fields internally.
- Rate-limit mapping has one adapter.
- Existing public behavior remains stable.
- Verification passes:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `PYTHONWARNINGS=error::ResourceWarning uv run pytest`
  - `uv run pytest --cov=src/codex_meter --cov-report=term-missing`
  - `uv run python -m build`

## Deferred Unless Time Remains

- Full hard mypy gate.
- Full hard Bandit gate.
- Forecast command extraction.
- Receipt command extraction.
- Live TUI internals beyond verification and obvious cleanup.
