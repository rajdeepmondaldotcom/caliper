# Changelog

All notable changes to Caliper. Newest on top.

## 0.0.1 — 2026-05-13

Initial public release.

### Added

- Local-first `caliper` CLI for reading Codex, Claude Code, Cursor, and
  Aider usage logs without login, upload, telemetry, or a daemon.
- Token, cache, credit, and API-dollar reporting by overview, day, week,
  month, session, billing block, project, model, vendor, PR, and commit.
- Cache-aware rate cards, opt-in pricing catalog refresh, schema export,
  receipt export, Prometheus metrics, Grafana dashboard JSON, budget checks,
  forecasts, compare/what-if reports, and model/tier advice.
- Parse caching, health checks, rate-limit views, shell statusline output,
  live local usage view, docs site, and VS Code status bar extension source.

### Compatibility

- PyPI distribution: `caliper-ai`.
- CLI command: `caliper`.
- Python import path: `caliper`.
- JSON output includes the top-level `caliper` envelope with
  `schema_version: 1`.
