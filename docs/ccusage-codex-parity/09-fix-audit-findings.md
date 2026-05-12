# Phase 9 - Fix Audit Findings

## Findings Addressed

The Phase 8 audit did not identify code or documentation gaps requiring fixes.

## Final State

- `CODEX_HOME` controls default Codex data paths unless config or CLI paths
  override it.
- Usage events retain model source and fallback model flags.
- Aggregates retain fallback counts and row-local model/tier breakdowns.
- JSON reports expose `model_sources`, `fallback_model_events`, and
  `model_breakdowns`.
- README documents the new behavior.
- Tests, lint, diff checks, and focused CLI smokes pass.

No additional code changes were required after the Phase 8 audit.

