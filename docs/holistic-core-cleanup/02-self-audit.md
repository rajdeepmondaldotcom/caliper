# Phase 2 - Self-Audit

## Audit Scope

This audit checks the Phase 1 plan against the current code and test suite. It
focuses on implementation blockers, circular-import risks, missing tests, and
quality-gate assumptions.

Commands run during audit:

- `rg` over CLI private helper usage in `tests/`
- `rg` over parser/cache tuple and rate-limit usage
- `rg` over aggregation and rendering behavior checks
- `uvx mypy src/codex_meter --ignore-missing-imports --python-version 3.11`
- `uvx bandit -q -r src/codex_meter`
- `PYTHONWARNINGS=error::ResourceWarning uv run pytest`
- `uv run python -m build`

## Findings

### 1. Parser record dataclass cannot live in `parser.py`

Phase 1 says to add a `ParsedSessionRecord` near parser/cache code. The current
import direction is:

- `parser.py` imports `ParseCache` from `parse_cache.py`
- `parse_cache.py` imports model dataclasses from `models.py`

If `ParsedSessionRecord` lives in `parser.py`, then `parse_cache.py` must import
`parser.py`, creating a circular import. The record type must live in `models.py`
or a tiny independent module.

Revision needed:

- Put `ParsedSessionRecord` in `models.py`.
- Update `parse_cache.py` and `parser.py` to use it.
- Keep JSON cache keys `event`, `reset`, and `sample` stable.

### 2. Rate-limit mapping should be normalized before records are built

Phase 1 correctly identifies duplicate mapping, but the implementation detail is
underspecified. `rate_limit_sample()` currently returns a `RateLimitSample`, while
`_parse_session` separately builds `UsageEvent` rate-limit fields.

Revision needed:

- Add an internal normalized structure or helper for raw rate-limit dictionaries.
- Use it to construct both `RateLimitSample` and `UsageEvent`.
- Preserve field names and raw value behavior because outputs currently expose
  these values directly.

### 3. CLI private helper tests need to move with the extracted interfaces

`tests/test_cli_helpers.py` imports several private helpers from `codex_meter.cli`:

- `_records_to_csv`
- `_records_to_markdown`
- `_fetch_rate_sources`
- `_extract_models_from_text`
- `_dedupe_models`
- `_check_state_db_readable`
- `_check_rates_file`
- `_build_prometheus_snapshot`

If helpers move without test updates, tests will still pass only by leaving
compatibility wrappers in `cli.py`, which defeats the cleanup.

Revision needed:

- Move tests to import the new module interfaces directly.
- Keep compatibility wrappers only if they are needed for internal command
  readability, not for test convenience.

### 4. Static typing is not ready to become a gate without Decimal cleanup

Mypy found 73 errors in source. Most are not behavioral bugs; they come from the
current pattern of accepting `Decimal | float` in dataclasses and normalizing to
`Decimal` in `__post_init__`. Mypy still sees the fields as unions after runtime
normalization.

Examples:

- `CostTotals` arithmetic mixes `Decimal | float`.
- `Rates.effective_reasoning_output` returns a union to mypy.
- Formatter helpers expect `float` while callers pass Decimal-backed fields.
- CLI scenario records are inferred as `list[object]`.

Revision needed:

- Do not add mypy as a required gate until Decimal field typing is cleaned up.
- Prefer a dedicated Decimal typing cleanup if time permits.
- If a static type tool is added now, it should be informational or scoped.

### 5. Bandit can inform security cleanup, but should not be added blindly

Bandit reported no high-severity findings, but it did report:

- `subprocess` import and static `git`/`codex` subprocess calls in `cli.py`.
- `urllib.request.urlopen` in the explicit network-only `rates refresh` path.
- Dynamic SQL string assembly in `load_thread_metadata()`.

The subprocess calls are static command invocations with `shell=False`; the
network call uses static pricing-source URLs behind `--allow-network`; the SQL
query builds column expressions only from a fixed allowlist. These are explainable,
but Bandit will need either targeted suppressions or configuration.

Revision needed:

- Treat Bandit as research/audit input.
- If adding a Bandit gate, first add targeted `# nosec` comments with local
  explanations for static commands, URL source validation, and fixed-schema SQL.
- Do not fail CI on known intentional patterns without suppressing them.

### 6. Prometheus snapshot construction remains a CLI responsibility in Phase 1

`_build_prometheus_snapshot()` is a 49-line CLI helper with moderate complexity.
Phase 1 names it as shallow but does not include it in the implementation order.

Revision needed:

- Either extract it to a module such as `prom_snapshot.py`, or explicitly defer it.
- Since `prom_export.py` already owns metric text and server behavior, a good
  target is a pure `snapshot_from_options()` helper outside `cli.py`.

### 7. Forecast command extraction is less urgent than compare/what-if

`forecast()` is long, but most real calculation already lives in `forecasts.py`.
The command body mainly builds two projections and renders four formats.

Revision needed:

- Do not prioritize forecast extraction before rate audit, health checks, parser
  records, and scenario math.
- Consider extracting a forecast payload helper only if the main extractions leave
  time.

### 8. `Aggregate.add_event` refactor is safe but must remain internal

Aggregation tests cover project paths, model breakdowns, fallback model counters,
and JSON render behavior. This gives enough protection for internal method
extraction.

Revision needed:

- Keep `Aggregate.add_event()` as the only public mutation method.
- Add private methods rather than moving aggregation attribution into another
  module.

### 9. Existing root phase docs are for prior work

The repo already contains root-level `docs/01-...` through `docs/09-...` files,
plus feature-specific phase folders. Overwriting those would destroy useful
history.

Revision needed:

- Keep this cleanup under `docs/holistic-core-cleanup/`.
- Do not rewrite prior phase documents.

### 10. Build and warning-as-error tests are already healthy

`PYTHONWARNINGS=error::ResourceWarning uv run pytest` passes, and
`uv run python -m build` passes. This supports refactoring without needing an
initial bugfix phase.

Revision needed:

- Preserve this verification as an acceptance criterion.
- Add targeted tests before moving interfaces.

## Audit Decision

The Phase 1 direction is valid, but the plan needs tightening before
implementation:

- place `ParsedSessionRecord` in `models.py`;
- add a concrete rate-limit normalization helper;
- extract Prometheus snapshot construction or explicitly defer it;
- move tests to the new modules rather than keeping private CLI-test coupling;
- postpone a hard mypy gate until Decimal typing is improved;
- use Bandit findings as targeted security cleanup, not a blind CI gate.
