# Phase 6 - Final Consolidated Implementation Plan

This is the implementation source of truth for the cleanup. It consolidates the original plan, self-audit, research refinements, and final code audit.

## Final Audit Summary

The current codebase is healthy: linting, formatting, tests, warning checks, coverage, and package builds all pass. The cleanup should therefore optimize structure and maintainability, not repair broken behavior.

The final audit found four concrete pressure points:

1. `src/codex_meter/cli.py` owns too much non-CLI logic. Tests import private helpers from it, which keeps command support logic coupled to Typer.
2. Parser/cache records are positional tuples. They work, but they make parser intent harder to review and make future cache changes more error-prone.
3. Rate-limit field mapping is repeated between usage events and samples.
4. `Aggregate.add_event` is correct but does too many unrelated mutations in one method.

The audit also confirmed these guardrails:

- Do not change command names, option names, default values, or output schemas.
- Do not change pricing semantics or the embedded rate model set as part of cleanup.
- Do not add hard mypy or Bandit gates in this pass.
- Keep cache payload compatibility for existing parse-cache rows.

## Implementation Slices

### Slice 1 - Planning and Agent Context

Commit the planning docs and tracked agent context created for this cleanup:

- `docs/agents/domain.md`
- `docs/agents/issue-tracker.md`
- `docs/agents/triage-labels.md`
- `docs/holistic-core-cleanup/*.md`

If a tracked `CONTEXT.md` is added, it should summarize the project purpose, invariants, and architecture in a short stable form.

### Slice 2 - Output Helpers

Create `src/codex_meter/output.py` with:

- `json_default`
- `json_dumps`
- `amount_fields`
- `records_to_csv`
- `records_to_markdown`

Update `cli.py` to import these helpers. Update tests so pure output helper assertions import `codex_meter.output` directly.

### Slice 3 - Rate Audit Helpers

Create `src/codex_meter/rate_audit.py` with:

- fetched-rate path lookup;
- source URL validation;
- rate source fetching;
- text and HTML model extraction;
- model dedupe;
- embedded and fetched rate payload generation;
- rate discrepancy calculation.

The network fetch path must allow only `http` and `https` schemes, fail softly per source, and keep `rates refresh` behavior intact.

### Slice 4 - Doctor Health Checks

Create `src/codex_meter/health.py` with:

- `HealthCheck`;
- Codex CLI version check;
- clock skew check;
- rate-card age check;
- state DB readability check;
- rates-file check;
- Python version check;
- health-report assembly for the `doctor` command.

Update CLI rendering only; keep output schemas unchanged.

### Slice 5 - Prometheus Snapshot

Create `src/codex_meter/prom_snapshot.py` with:

- `build_prometheus_snapshot(options: RuntimeOptions)`.

Update `export-prometheus` to use the module. Update direct tests to import from the module.

### Slice 6 - Scenario Math

Create `src/codex_meter/scenarios.py` for low-risk pure calculations:

- event filtering by interval;
- interval aggregation;
- interval summary dictionaries;
- compare delta calculation;
- what-if aggregate calculation where behavior can be preserved exactly.

Leave Typer argument parsing and Rich/JSON/CSV/Markdown rendering in `cli.py`.

### Slice 7 - Parser Record Explicitness

Add `ParsedSessionRecord` to `models.py` and update:

- `parser._parse_session`;
- parser cache encode/decode;
- `load_usage` iteration;
- parser/cache tests.

Cache JSON keys remain `event`, `reset`, and `sample` so existing persisted cache rows continue to decode.

### Slice 8 - Rate-Limit Normalization

Add a parser helper that converts raw `rate_limits` dictionaries into the exact primary/secondary fields used by `UsageEvent` and `RateLimitSample`.

Use it in both places without changing field values.

### Slice 9 - Aggregate Simplification

Refactor `Aggregate.add_event` into small private helpers without changing public dataclasses or aggregate totals.

### Slice 10 - Quality Configuration and Verification

After code changes, run:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `uv run pytest --cov=src/codex_meter --cov-report=term-missing`
- `PYTHONWARNINGS=error::ResourceWarning uv run pytest`
- `uv run python -m build`

Add a conservative coverage floor only if the post-refactor coverage remains above it.

## Phase 8 and Phase 9 Expectations

The post-implementation audit must compare the final code against this document. Any missing slice, behavior deviation, test gap, or quality-gate issue must be listed explicitly and either fixed in Phase 9 or documented as intentionally deferred with a reason.
