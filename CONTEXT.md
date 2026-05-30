# Caliper Context

`caliper` is an offline-first Python CLI/library that turns local AI coding
session data into usage intelligence. It reads OpenAI Codex, Claude Code,
local trails today. Its deepest source integration remains Codex: local JSONL
session logs, optional Codex SQLite metadata, user config, embedded pricing
assumptions, and rate-limit samples. It does not scrape
billing pages, require account login, or upload local usage.

## Core Invariants

- Local evidence is the source of truth. Commands must work without network access unless the user explicitly requests network refresh behavior.
- Public CLI behavior is part of the contract: command names, option names, default values, output fields, and exit codes should change only intentionally.
- Pricing math is Decimal-first. Float values are acceptable at output boundaries, but cost and credit calculations should preserve exact Decimal values internally.
- Embedded pricing and source metadata are auditable assumptions, not a billing ledger.
- Parser cache rows must remain backward compatible unless the cache version is deliberately bumped.
- Report commands should separate loading, aggregation, pricing, rendering, and CLI orchestration.

## Vendors

Caliper is built around a vendor-neutral record. Every `UsageEvent` and
`RateLimitSample` carries a `vendor` field. Shipped parsers are
`openai-codex` and `claude-code`. Planned parsers populate the same record
shape, so reports, pricing, budgets, forecasts, and exports work cross-vendor
without restructuring.

Known vendor constants live in `caliper.models`:
`VENDOR_OPENAI_CODEX`, `VENDOR_CLAUDE_CODE`, `VENDOR_COPILOT`,
`VENDOR_UNKNOWN`.

## Domain Terms

- Usage event: one parsed usage delta tied to a vendor, session, timestamp, model, tier, project, and source metadata.
- Rate-limit sample: a parsed snapshot of primary/secondary Codex rate-limit windows.
- Aggregate: token totals, cost totals, cache savings, model breakdowns, source counts, and project attribution for a selected window.
- API-equivalent dollars: an estimate based on OpenAI API model pricing.
- Credits: Codex subscription credit estimates derived from the embedded Codex rate card.
- Pricing status: exact, estimated, or unpriced signal derived from aggregate cost metadata.

## Architecture Map

- `config.py`: resolves CLI/config-file/default runtime options.
- `parser.py`: reads local Codex logs and state DB metadata into `LoadResult`.
- `parse_cache.py`: caches parsed Codex session records and vendor events behind a versioned SQLite sidecar.
- `models.py`: shared dataclasses and Decimal helpers.
- `pricing.py`: embedded rate cards, overrides, and per-event cost calculations.
- `aggregation.py`: groups usage events into report-ready aggregates.
- `render.py`: report JSON/table/limit rendering.
- `cli.py`: Typer command surface and command orchestration.
- `statusline.py`, `live.py`, `budgets.py`, `insights.py`, `forecasts.py`, `exporters.py`, `prom_export.py`, `windows.py`: focused feature modules.

## Cleanup Preference

Improve the codebase by deepening existing seams instead of redesigning the system. Prefer small pure modules behind the CLI, explicit data records, focused tests, and conservative quality gates.
