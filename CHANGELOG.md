# Changelog

All notable changes to Caliper. Newest on top.

## Unreleased

### Added

- New optional `[tui]` extra. `pip install 'caliper-ai[tui]'` adds
  `textual>=8.2,<9` and `watchdog>=4.0,<7`. Base install stays
  zero-extra.
- `caliper tui` command boots an interactive Textual workspace built
  on the existing pure modules (`parser.load_usage`,
  `aggregate_*`, `pricing.RateCard`, `windows.compute_window_state`,
  `insights.build_insights_from`). Today the Home screen renders a
  real three-window cost overview, primary/secondary credit windows,
  insights feed, and recent sessions. Twelve other screens are
  reachable via `1..9` but currently show placeholders; the workspace
  fills in over subsequent releases.
- `caliper tui --demo` boots against a deterministic synthetic
  fixture so the experience is reviewable without local logs.
- New public helpers reused by both CLI and TUI:
  `caliper.progress.ParseProgress`,
  `caliper.insights.build_insights_from`,
  `caliper.vendors.vendor_file_count`,
  `caliper.parse_cache.ParseCache.clear`,
  `caliper.budgets.serialize_budgets`,
  `caliper.config.TuiConfig` + `load_tui_config` + `serialize_tui_config`,
  `caliper.humanize.sparkline`,
  `caliper.exporters.session_compat_json`, and
  `caliper.scenarios.days_for_interval`.

### Changed

- Bumped `rich` floor to `>=14.2.0` to align with Textual's own
  minimum (no observable CLI rendering changes).
- Hoisted overview-window aggregation into the pure
  `aggregate_overview_windows` helper; `caliper overview` is the
  first caller and the TUI reuses it directly.

### Internal

- See `docs/textual-tui/` for the nine-phase plan, audits, research,
  and post-implementation log driving this work.

## 0.0.2 - 2026-05-13

Recreate the PyPI project after deleting the pre-rewrite package history.

### Changed

- Republished the initial Caliper release under a new PyPI version because
  PyPI permanently reserves deleted distribution filenames.

## 0.0.1 - 2026-05-13

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
