# Phase 1 - Initial Implementation Plan

## Goal

Improve `codex-meter` as a Python library and CLI without adding user-facing features.
The target is simpler, deeper modules; preserved public behavior; stronger tests; and
clearer maintenance surfaces for future Codex usage analysis work.

The source of truth is the current repository. This plan is grounded in the files,
tests, and workflows present on 2026-05-13.

## Current State

Verification baseline:

- `uv run ruff check .` passes.
- `uv run ruff format --check .` passes.
- `uv run pytest` passes with 192 tests.
- `uv run pytest --cov=src/codex_meter --cov-report=term-missing` reports 87% coverage.
- `uvx vulture src tests --min-confidence 80` reports no dead-code findings.
- `uvx radon cc src/codex_meter -s -a` reports average complexity A, but flags several
  large or complex modules.

Tracked package shape:

- `src/codex_meter/parser.py` streams local Codex JSONL sessions, joins optional
  `state_5.sqlite` metadata, resolves service tiers, extracts usage deltas, and
  emits `LoadResult`.
- `src/codex_meter/parse_cache.py` caches parsed session payloads in SQLite.
- `src/codex_meter/models.py` owns shared dataclasses and aggregate mutation.
- `src/codex_meter/pricing.py` owns embedded model cards, rate overrides, exact
  Decimal costs, service-tier normalization, and long-context rules.
- `src/codex_meter/aggregation.py` turns events into totals and grouped reports.
- `src/codex_meter/render.py` formats grouped reports and limits in table, JSON,
  CSV, and Markdown.
- `src/codex_meter/statusline.py`, `windows.py`, `forecasts.py`, `budgets.py`,
  `insights.py`, `exporters.py`, `prom_export.py`, `live.py`, and `intervals.py`
  are mostly focused modules with public behavior already covered by tests.
- `src/codex_meter/cli.py` is the main shallow module: 2,521 lines, many command
  bodies, rate-card audit scraping, doctor checks, budget orchestration, compare
  and what-if orchestration, output helpers, and Prometheus snapshot construction.

Test shape:

- Tests exercise parser behavior through real JSONL fixtures and real SQLite.
- CLI tests use `typer.testing.CliRunner`.
- Pure modules have direct tests for pricing, aggregation, intervals, windows,
  budgets, forecasts, exporters, statusline, parse cache, and subscriptions.
- Coverage gaps are mostly in `cli.py`, `live.py`, `render.py`, and parser edge
  branches, not in the core happy path.

## Architecture Map

The current pipeline is:

1. CLI/config layer builds `RuntimeOptions`.
2. Parser loads session events and rate-limit samples into `LoadResult`.
3. Aggregation prices and groups events using `RateCard`.
4. Renderers serialize aggregates or rate-limit samples.
5. Command-specific modules produce extra views: insights, forecasts, budgets,
   statusline, live frames, receipts, Grafana, and Prometheus.

The good seams already present:

- `RuntimeOptions` is the common command configuration interface.
- `LoadResult` is the parser output interface.
- `Aggregate` is the report-row interface.
- `RateCard` is the pricing interface.
- Renderer functions are mostly pure string-producing functions.

The shallow seams:

- `cli.py` knows too much about rate-source fetching, HTML extraction, doctor
  checks, Prometheus metric construction, output helper serialization, and
  interval comparison math.
- `parser.py` has duplicated rate-limit field mapping between `RateLimitSample`
  and `UsageEvent`, and `_parse_session` returns anonymous tuples.
- `models.Aggregate.add_event` mixes token/cost accumulation, project attribution,
  source tracking, first/last seen timestamps, long-context counters, and nested
  model breakdown mutation.
- Some helper functions are only testable by importing private functions from
  `cli.py`, which is a sign the real interface lives in the wrong module.

## Deepening Opportunities

### 1. Extract command support modules from `cli.py`

Files involved:

- `src/codex_meter/cli.py`
- new `src/codex_meter/output.py`
- new `src/codex_meter/rate_audit.py`
- new `src/codex_meter/health.py`
- new `src/codex_meter/scenarios.py`
- tests currently importing `codex_meter.cli` private helpers

Problem:

`cli.py` is the largest and most complex module. It is doing routing and domain
work at the same time. That lowers locality because changes to rate refresh,
doctor checks, compare, what-if, budget output, and Prometheus metrics all require
editing the command surface.

Solution:

- Move generic JSON/CSV/Markdown record helpers and exact amount field helpers to
  `output.py`.
- Move `rates refresh` fetch/extract/dedupe/discrepancy logic to `rate_audit.py`.
- Move doctor checks and health payload construction to `health.py`.
- Move pure compare and what-if calculations to `scenarios.py`.
- Keep Typer command functions in `cli.py`, but make them orchestration wrappers.

Benefits:

- Better locality: rate audit changes stop touching command routing.
- Better leverage: pure modules expose small interfaces that tests can hit without
  `CliRunner`.
- Lower complexity in `cli.py` without changing command names, flags, or output
  schemas.

### 2. Make parser records explicit

Files involved:

- `src/codex_meter/parser.py`
- `src/codex_meter/parse_cache.py`
- `tests/test_parser.py`
- `tests/test_parse_cache.py`

Problem:

`_parse_session` and parse cache pass records as `(UsageEvent | None, bool,
RateLimitSample | None)` tuples. The fields are meaningful but positional.
That makes parser-cache compatibility and future parser maintenance harder than
needed.

Solution:

- Add a frozen `ParsedSessionRecord` dataclass near parser/cache code.
- Replace anonymous tuples with named fields: `event`, `counter_reset`, `sample`.
- Keep cache payload shape backward-compatible by encoding the same JSON keys.

Benefits:

- The parser interface becomes self-documenting.
- Cache tests can assert meaning, not tuple positions.
- Future changes to parse records have a clear compatibility seam.

### 3. Centralize rate-limit field mapping

Files involved:

- `src/codex_meter/parser.py`
- `src/codex_meter/models.py`
- `tests/test_parser.py`
- `tests/test_limits_formats.py`

Problem:

`rate_limit_sample()` maps rate-limit fields once, then `_parse_session` maps the
same fields again into `UsageEvent`. This duplication is small but risky because
Codex limit samples are an evolving local-log format.

Solution:

- Build one small helper that extracts normalized rate-limit fields from a raw
  `rate_limits` object.
- Use it for both `RateLimitSample` and `UsageEvent`.
- Preserve all existing field names and values.

Benefits:

- The Codex rate-limit log shape has one adapter.
- Limits output and usage events cannot drift.
- Parser tests become more targeted.

### 4. Reduce aggregate mutation complexity

Files involved:

- `src/codex_meter/models.py`
- `src/codex_meter/aggregation.py`
- `tests/test_aggregation.py`
- `tests/test_formats.py`

Problem:

`Aggregate.add_event` is the highest-complexity method in `models.py`. It mixes
several independent responsibilities behind one mutation method.

Solution:

- Extract small private methods on `Aggregate` for:
  - token/cost/model/tier counters;
  - project and source attribution;
  - first/last seen timestamps;
  - nested model breakdown update.
- Keep `Aggregate.add_event` as the public mutation interface.

Benefits:

- No caller changes.
- Lower cognitive load inside the most important report-row object.
- Tests remain behavior-focused through aggregation and rendering.

### 5. Strengthen quality gates without making development noisy

Files involved:

- `pyproject.toml`
- `.github/workflows/ci.yml`
- `tests/`

Problem:

The repo has Ruff, tests, and coverage tooling, but CI does not enforce coverage,
and there is no static type check even though the package ships `py.typed`.

Solution:

- Add a moderate coverage floor that current behavior already clears.
- Add `mypy` with a pragmatic configuration if the current code can pass without
  contorting readable code.
- Keep Ruff as the first-line lint/format tool.
- Do not add heavyweight framework dependencies.

Benefits:

- The typed-library promise has an enforceable check.
- Future refactors have a measurable floor.
- The quality gate supports cleanup instead of becoming the cleanup.

### 6. Add a project domain context

Files involved:

- new `CONTEXT.md`
- `docs/agents/domain.md`

Problem:

The repo has a strong `CLAUDE.md` guide, but it is locally ignored and not part of
the tracked package documentation. The architecture skills prefer a durable domain
glossary.

Solution:

- Add a concise tracked `CONTEXT.md` describing domain terms: session log, state
  DB, usage event, rate-limit sample, rate card, service tier, project attribution,
  aggregate, report, receipt, statusline, and live frame.

Benefits:

- Future architecture work has stable vocabulary.
- The tracked repo carries its own domain language.
- It avoids rediscovering core concepts from code every time.

## Edge Cases To Preserve

- Missing session root produces a warning, not a crash.
- Missing or unreadable `state_5.sqlite` does not block JSONL parsing.
- Older state DB schemas with fewer columns still load.
- JSONL parse errors are skipped line-by-line.
- `last_token_usage` and `total_token_usage` both remain supported.
- Out-of-window total-token events still seed in-window deltas.
- Token counter resets still warn once per path.
- Dedupe keeps identical usage from different sessions.
- `turn_context.cwd` beats state DB cwd for event-scoped project attribution.
- Privacy defaults remain intact: prompt labels stay redacted unless explicitly
  requested.
- Exact Decimal fields in JSON stay present alongside numeric compatibility fields.
- Rate-limit-only events stay available to `limits` and window math without
  becoming usage totals.
- `rates refresh` remains opt-in network behavior behind `--allow-network`.
- Doctor and budgets keep severity-driven exit codes.
- Prometheus exporter keeps the default `127.0.0.1` bind.

## Initial Implementation Order

1. Add tracked domain and agent context docs.
2. Add behavior-lock tests around current public output where extraction will move
   logic out of `cli.py`.
3. Extract generic output helpers.
4. Extract rate-audit logic from `cli.py`.
5. Extract doctor health-check logic from `cli.py`.
6. Extract pure compare and what-if calculations from `cli.py`.
7. Make parser records explicit and centralize rate-limit mapping.
8. Refactor `Aggregate.add_event` internally without changing callers.
9. Add or tune quality gates only after the code is green.
10. Run the full verification matrix and document any residual gaps.

## Non-Goals

- No new user-facing CLI commands.
- No changes to default offline behavior.
- No new default network calls.
- No changes to pricing assumptions unless required by verified source drift.
- No database writes to Codex-owned files.
- No Terraform commands.
- No push to remote.

## Acceptance Criteria

- All existing command names, flags, output formats, and exit-code contracts are
  preserved.
- `uv run ruff check .` passes.
- `uv run ruff format --check .` passes.
- `PYTHONWARNINGS=error::ResourceWarning uv run pytest` passes.
- Coverage remains at or above the existing 87% baseline unless a documented,
  justified tradeoff is made.
- `uv run python -m build` passes.
- Every implementation change is committed locally in logical units.
