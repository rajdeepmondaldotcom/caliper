# Phase 1 - Initial Implementation Plan

## Goal

Audit `codex-meter` against `@ccusage/codex` 18.0.11 and implement the missing
Codex-usage features that fit this Python codebase without weakening the
existing architecture.

The architecture anchor remains this repository:

- parse local Codex evidence;
- enrich usage events once;
- aggregate through shared pure functions;
- render stable table/JSON/CSV/Markdown outputs;
- stay offline by default except explicit rate-card refresh.

`@ccusage/codex` is a benchmark, not a template to port wholesale.

## Current Codebase Grounding

The current implementation already exceeds the referenced package in several
areas:

- `parser.py` reads `~/.codex/sessions/**/*.jsonl`, joins `state_5.sqlite`,
  extracts token deltas, service tier, plan type, limit bucket metadata, model
  context windows, and rate-limit samples.
- `parse_cache.py` stores parsed session records in a sidecar SQLite cache.
- `pricing.py` uses embedded Codex credit/API rates, exact decimal math,
  long-context rules, fast multipliers, local rate overrides, and pricing
  warnings.
- `aggregation.py` supports day, week, month, session, project, model/tier, and
  total aggregation.
- `render.py` emits table, JSON, CSV, and Markdown reports, including project
  inventories and subscription metadata.
- `cli.py` exposes overview, daily, weekly, monthly, session, project, models,
  limits, insights, tail, doctor, init, rates, forecast, compare, what-if,
  statusline, live, receipt, Prometheus, Grafana, and budgets.

## `@ccusage/codex` Feature Audit

Primary package features observed from the npm tarball, CLI help, bundled
source, and public docs:

- commands: default daily, `daily`, `monthly`, `session`;
- date filtering: `--since`, `--until`;
- timezone grouping: `--timezone`;
- locale formatting: `--locale`;
- JSON output: `--json` / `-j`;
- offline pricing toggle: `--offline` / `--no-offline`;
- compact tables and color toggles;
- `CODEX_HOME` environment support for finding `sessions`;
- per-model token and cost summaries inside each JSON row;
- legacy fallback model handling when Codex logs lack model metadata;
- cached input token accounting;
- LiteLLM pricing refresh/fallback behavior.

## Gap Analysis

Already covered or exceeded:

- daily, monthly, and session reports;
- additional weekly, overview, project, model/tier, limits, insight, forecast,
  compare, budget, export, live, and statusline commands;
- `--since`, `--until`, `--timezone`, compact mode, path overrides;
- JSON plus CSV and Markdown output;
- cached input accounting;
- Codex-specific credit pricing and API-dollar estimates;
- project/workspace metadata from JSONL and SQLite;
- rate-limit bucket tracking;
- offline-first operation.

Missing and selected:

1. `CODEX_HOME` default path support.
   - `config.py` currently hardcodes `~/.codex`.
   - Users who run Codex with `CODEX_HOME=/other/home` must pass three explicit
     paths or config keys.
   - This is low risk because CLI flags and config files should keep precedence.

2. Model-source and fallback visibility.
   - `parser.py` falls back to `options.default_model` when logs/state do not
     provide a model, but the output does not say that the model was inferred.
   - `@ccusage/codex` marks fallback model rows in JSON.
   - This should become first-class event and aggregate metadata so pricing
     explainability is visible everywhere JSON is used.

3. Per-row model breakdowns in JSON.
   - `codex-meter` has a top-level `model_mode` inventory for the selected
     window, but daily/monthly/session/project rows do not embed their own
     model/tier contribution details.
   - `@ccusage/codex` includes per-model usage objects in each JSON row.
   - The Python implementation should expose richer row-level
     `model_breakdowns` without changing table, CSV, or Markdown schemas.

Deferred intentionally:

- `--locale`: current labels are ISO-like and stable for reporting. Locale
  formatting is presentation-only and would introduce platform-dependent
  behavior without improving analytics.
- live LiteLLM pricing fetch by default: this codebase has deliberately chosen
  explicit network use through `rates refresh --allow-network`.
- color flags: Rich already handles terminal color negotiation, and this is not
  an analytics gap.
- full `--json` compatibility alias across all commands: `--format json` is
  already more general. It can be added later as a compatibility layer, but it
  is not required to improve the data model.

## Initial Implementation Shape

1. Configuration
   - Add a `codex_home()` helper that reads `CODEX_HOME`.
   - Default `session_root`, `state_db`, and `codex_config` from that home.
   - Preserve explicit CLI/config path precedence.
   - Ignore empty `CODEX_HOME`.

2. Parser and models
   - Add `model_source` and `model_is_fallback` to `UsageEvent`.
   - Resolve model with explicit source labels:
     `turn_context`, `state-db`, then `default`.
   - Treat `default` as fallback.
   - Increment parser cache version.
   - Harden parse-cache event decoding to ignore future keys.

3. Aggregation
   - Add aggregate-level `model_sources` and `fallback_model_events`.
   - Add a small `ModelBreakdown` dataclass for row-local model/tier totals,
     costs, cache savings, model sources, and fallback counts.
   - Populate breakdowns in `Aggregate.add_event()` using already-computed
     event costs.

4. Rendering
   - Add JSON-only `model_sources`, `fallback_model_events`, and
     `model_breakdowns` to aggregate payloads.
   - Preserve existing numeric fields and add exact decimal companions in each
     model breakdown.
   - Leave table, CSV, and Markdown output unchanged.

5. Documentation
   - Document `CODEX_HOME` and model fallback visibility in README.
   - Mention JSON row-level model breakdowns.

6. Tests
   - Config test for `CODEX_HOME` defaults and CLI path precedence.
   - Parser tests for model source from `turn_context`, `state-db`, and default.
   - Aggregation tests for model breakdown totals and fallback counts.
   - Format tests for JSON `model_breakdowns`.
   - Parse-cache test for future event keys.

## Edge Cases

- `CODEX_HOME` set to whitespace: ignore and use `~/.codex`.
- Config file sets paths while `CODEX_HOME` is set: config wins unless CLI path
  overrides it.
- State DB missing but `turn_context.model` exists: source is `turn_context`.
- `turn_context.model` missing but SQLite model exists: source is `state-db`.
- Both missing: source is `default`, fallback count increments.
- Unknown fallback model pricing: existing pricing warnings still apply.
- Multiple models/tiers in one day: row-level model breakdowns expose each
  model/tier contribution.
- Existing parse-cache rows: version bump forces reparse; decoder tolerance
  protects future cache payloads.

