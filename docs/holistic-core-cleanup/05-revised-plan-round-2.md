# Phase 5 - Revised Plan, Round 2

This revision incorporates Phase 4 research as constraints and refinements only. The architecture from Phase 1 through Phase 3 remains the source of truth: keep the CLI contract stable, deepen existing seams, and simplify the core without adding features.

## Research-Informed Constraints

1. Keep the existing `src/` layout, package metadata, and `codex-meter` console script. This already matches current PyPA guidance and does not need redesign.
2. Keep Typer as the CLI boundary. The cleanup should move command internals behind focused modules while leaving command names, options, and output shapes intact.
3. Preserve Decimal-first pricing and credit arithmetic. Cost reporting is accounting-like, and binary floating point would make exactness worse.
4. Treat mypy as a future gradual-typing effort, not as a new hard gate in this cleanup. The current code has too many legacy type-shape issues around Decimal coercion to make a whole-package gate useful without a separate typing pass.
5. Treat Bandit as a targeted audit signal. The cleanup should fix or annotate real risks but should not add a noisy security gate until findings are intentionally triaged.
6. Add only conservative quality enforcement. A coverage floor is acceptable because the current project already reports healthy coverage, but it must leave room for platform-specific test variation.

## Finalized Refactor Targets

### CLI Decomposition

Extract pure helpers from `src/codex_meter/cli.py` into focused modules:

- `output.py`: JSON encoding, amount-field expansion, CSV rendering, Markdown rendering.
- `rate_audit.py`: rate-source fetching, source parsing, model dedupe, embedded/fetched rate payload creation, discrepancy calculation, fetched-rate path lookup.
- `health.py`: doctor checks and health-report assembly.
- `prom_snapshot.py`: Prometheus snapshot assembly.
- `scenarios.py`: interval summaries, compare math, and what-if calculations where extraction is low-risk.

The CLI remains the orchestration layer: parse options, call lower-level modules, render results, and preserve user-facing behavior.

### Parser Explicitness

Add `ParsedSessionRecord` in `models.py`, then update parser/cache plumbing to pass named records instead of positional tuples. This avoids circular imports and makes cache records, usage events, counter resets, and rate-limit samples self-documenting.

### Rate-Limit Mapping

Centralize rate-limit extraction so parser logic does not duplicate primary/secondary window mapping for `UsageEvent` and `RateLimitSample`. Preserve field names and semantics exactly.

### Aggregate Mutation

Split `Aggregate.add_event` into small private helpers for token totals, cost totals, attribution, source tracking, and model breakdown updates. This keeps the public behavior intact while reducing cyclomatic complexity.

### Security Tightening

When fetching official rate sources, validate URLs before network access:

- allow only `https://` and `http://` schemes;
- keep source URLs anchored to the existing configured source list;
- return structured source errors instead of raising for invalid URLs;
- annotate unavoidable subprocess/network static-analysis findings only after the code path is explicit and bounded.

### Quality Gates

Keep the current fast gates:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `uv run pytest --cov=src/codex_meter --cov-report=term-missing`
- `PYTHONWARNINGS=error::ResourceWarning uv run pytest`
- `uv run python -m build`

Add a conservative coverage floor only if post-refactor coverage remains comfortably above it. Do not add hard mypy or Bandit gates in this cleanup.

## Implementation Order

1. Commit planning/context docs.
2. Extract output helpers and update direct helper tests.
3. Extract rate-audit logic and add URL validation.
4. Extract doctor health checks.
5. Extract Prometheus snapshot assembly.
6. Extract low-risk scenario math helpers.
7. Add `ParsedSessionRecord` and centralize rate-limit mapping.
8. Simplify `Aggregate.add_event` internally.
9. Add conservative quality configuration if verification supports it.
10. Run the full verification suite and commit each coherent unit locally.

## Acceptance Criteria

- All existing CLI commands and documented output formats remain compatible.
- Tests import pure helpers from their owning modules, not from `cli.py`.
- Parser/cache behavior remains compatible with existing cache payloads.
- Rate refresh still supports explicit network refresh and still fails soft when sources cannot be fetched.
- The docs explain both the plan and any deviations discovered during implementation.
- Local commits exist for each coherent unit of work.
