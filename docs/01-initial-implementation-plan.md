# Phase 1 - Initial Implementation Plan

## Goal

Audit the Codex-focused feature set against `https://github.com/ryoppippi/ccusage`
and improve `codex-meter` where the current code can give users clearer local
insight without changing the existing architecture.

The source of truth remains this repository. The external project is a feature
benchmark, not an architecture template.

## Current Codebase Grounding

`codex-meter` already has a deeper Codex-specific pipeline than the referenced
Codex companion CLI:

- `parser.py` reads `~/.codex/sessions/**/*.jsonl`, joins `state_5.sqlite`,
  extracts token deltas, rate-limit samples, model context windows, model names,
  and service tiers.
- `parse_cache.py` stores parsed sessions in a sidecar SQLite cache.
- `pricing.py` uses exact decimal math, embedded Codex credit/API rates, fast
  multipliers, long-context rules, local override files, and pricing-status
  warnings.
- `aggregation.py` groups by day, week, month, session, project, and model/tier.
- `render.py` emits table, JSON, CSV, and Markdown reports.
- `insights.py`, `forecasts.py`, `windows.py`, `budgets.py`, `live.py`,
  `exporters.py`, and `prom_export.py` provide higher-level operational views.
- `cli.py` exposes daily, weekly, monthly, session, project, models, limits,
  insights, tail, doctor, init, rates, forecast, compare, what-if, budgets,
  live, receipt, Prometheus, and Grafana commands.

## External Feature Baseline

The referenced repository has a Codex package with daily, monthly, and session
reports; date filtering; timezone selection; JSON output; compact tables;
offline pricing cache; cached-token accounting; per-model aggregation; and a
legacy model fallback.

The broader CLI family also has useful product patterns:

- compact statusline output for hooks;
- activity-window reports;
- project/instance-oriented analysis;
- structured JSON for downstream tooling;
- responsive tables and narrow-terminal modes;
- configuration layering and path overrides.

## Gap Analysis

Already covered:

- daily/monthly/session reports;
- JSON output, plus CSV and Markdown;
- compact table mode;
- date windows and timezone grouping;
- cached input accounting;
- per-model and per-tier aggregation;
- session JSONL parsing;
- offline default operation;
- local configuration;
- rich pricing status and warnings.

Partially covered:

- project analysis exists, but aggregate rows do not retain enough provenance
  for a user to explain which sessions, git refs, and time span created a row.
- live monitoring exists, but there is no single-line statusline command for
  editor hooks or shell prompts.
- exact Decimal math exists internally, but a few JSON command payloads still
  need exact string fields.
- rate-limit samples preserve plan type, but multiple Codex limit buckets can
  make the latest model-specific preview bucket mask the main subscription
  window.
- subscription plan strings are visible as raw `plan_type` values, but users
  need normalized plan metadata and warnings for promotional or legacy-plan
  ambiguity.

Not selected for this implementation:

- A full activity-block report. `codex-meter live` and `limits` already expose
  real Codex rate-limit samples, so a synthetic 5-hour block command should wait
  until project provenance is complete.
- JQ-in-process filtering. Users can pipe JSON to `jq`; embedding a query engine
  would add dependency and security surface.
- A live pricing fetcher by default. This project intentionally keeps normal
  reports offline and makes network access explicit through `rates refresh`.

## Implementation Strategy

1. Track these phase documents in `docs/`.
   - Remove the repository-level `docs/` ignore rule.
   - Replace stale local phase docs with the current implementation record.

2. Preserve exact amount fields in JSON payloads.
   - Keep existing float fields for compatibility.
   - Add `*_exact` string fields where compare, what-if, and budget outputs
     currently expose Decimal-backed amounts.

3. Enrich project/workspace provenance.
   - Extend `ThreadMeta` with optional local metadata already present in Codex
     state DB rows.
   - Update `turn_context` parsing to preserve event-scoped `cwd` when the
     SQLite state DB is missing or stale.
   - Extend `Aggregate` with session IDs, project paths/names, git refs,
     source/agent metadata, and first/last seen timestamps.
   - Add a top-level `projects` inventory and `workspace_coverage` metadata to
     JSON reports.
   - Keep table, CSV, and Markdown columns stable.

4. Enrich subscription and limit-window explainability.
   - Preserve `limit_id` and `limit_name` from Codex rate-limit samples.
   - Prefer the main `codex` bucket for default 5-hour/weekly window math.
   - Add normalized subscription-plan payloads and warnings to JSON/table
     reporting.

5. Add a compact statusline command.
   - Produce a single text line by default.
   - Add JSON output for automation.
   - Reuse `load_usage()`, `aggregate_total()`, `RateCard`, and
     `compute_window_state()` so the command has the same pricing and tier
     semantics as the rest of the CLI.

6. Update README and tests.
   - Document the new statusline command and richer project JSON.
   - Add focused parser, aggregation, format, parse-cache, and statusline tests.

## Edge Cases

- Missing state DB should not erase project attribution if JSONL `turn_context`
  has `cwd`.
- Older state DB schemas must continue to load.
- Older parse-cache payloads and future extra thread keys must not crash decode.
- JSON reports can contain local paths and git origins; README privacy language
  must keep warning users that exports are sensitive.
- Unknown subscription plans must be surfaced as warnings rather than guessed.
- Multiple rate-limit buckets must remain available in raw reports even when
  window summaries prefer the main bucket.
- Existing command output formats must remain stable unless JSON is explicitly
  enriched.
- Commit messages must be professional one-liners and must not name the
  benchmark project.

## Acceptance Criteria

- Tests cover exact amount JSON fields, project provenance, workspace coverage,
  cache compatibility, and statusline output.
- `codex-meter daily --format json` includes `projects` and workspace coverage.
- `codex-meter project --format json` exposes enriched project metadata.
- `codex-meter statusline` prints a compact single-line summary.
- Full tests and lint pass.
- Changes are committed locally and not pushed.
