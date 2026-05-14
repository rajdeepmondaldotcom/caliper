# Changelog

All notable changes to Caliper. Newest on top.

## 0.0.5 - 2026-05-14

Persona overhaul, round one. Caliper's terminal output starts speaking
in its own voice: short sentences, named constraints, decisions over
decoration. The work follows
`docs/persona-overhaul/01-plan.md`.

### Added

- `caliper.persona` module with `voice_lint(text)` and
  `voice_lint_strict(text)`. CI runs a dedicated voice-lint step on
  the persona tests so banned hype / fog / em-dashes never sneak into
  shipped copy. Importable from the top-level package.
- `caliper.pricing.model_vendor(model)` returns the canonical vendor
  label (`anthropic`, `openai`, `anysphere`, `google`, `mistral`,
  `meta`, `unknown`) for any model id. Every model in `MODEL_CARDS`
  resolves to a non-unknown vendor. Glyph helper
  `model_vendor_glyph(vendor)` returns a single character for dense
  screens.
- `Aggregate.model_vendors: set[str]` and
  `ModelBreakdown.model_vendor: str` populated everywhere aggregation
  runs.
- Classic table rendering shows a dim `Anthropic . OpenAI` chip under
  the model list. JSON gains `"model_vendor"` on every breakdown and
  `"model_vendors"` on every aggregate. Additive only.
- `Insight` carries `scope`, `evidence`, and `next_command` fields.
  Existing builders pin their scope and rewrite in voice. Two new
  templates: model-concentration and vendor-mix.
- Short primary flag names alongside every existing alias on shared
  `Annotated[...]` options. New flags reserved: `--only-vendor`,
  `--classic` / `--no-tui`. Every old flag survives as an alias
  forever.
- Textual-by-default branching for the `overview` (default) command:
  bare `caliper` on a TTY opens the workspace; `--format`, `--out`,
  `--classic`, or `CALIPER_NO_TUI=1` keep the classic Rich path
  byte-identical.

### Changed

- `caliper.render.write_output` swallows `BrokenPipeError` cleanly so
  `caliper daily --format json | head` no longer prints a traceback.

## 0.0.4 - 2026-05-14

Polish pass on the table output so reports scan cleanly in a 100-140
column terminal.

### Changed

- `Models` cells in every grouped table (`overview`, `daily`, `weekly`,
  `monthly`, `project`, `session`, `models`, …) now show at most three
  model names ranked by spend, joined with `·`, and suffixed with
  `+N` when more models exist. Vendor prefixes (`claude-`, `openai-`)
  are stripped so the cell fits without wrapping.
- Parser-issue warnings (e.g. Cursor files with no per-event token
  counts) no longer dump three full filesystem paths into every
  report. The summary form now reads "N files (run `caliper doctor`
  for examples)"; the verbose form remains available from
  `caliper.evidence.parser_issue_warning_verbose` for the doctor
  command.

## 0.0.3 - 2026-05-14

First release with the interactive Textual workspace baked into the
base install.

### Added

- `caliper tui` command boots an interactive Textual workspace built
  on the existing pure modules (`parser.load_usage`,
  `aggregate_*`, `pricing.RateCard`, `windows.compute_window_state`,
  `insights.build_insights_from`). Today the Home screen renders a
  real three-window cost overview, primary/secondary credit windows,
  insights feed, and recent sessions. Twelve other screens are
  reachable via `1..9` but currently show placeholders; the workspace
  fills in over subsequent releases.
- `textual>=8.2,<9` and `watchdog>=4.0,<7` are now required runtime
  dependencies of `caliper-ai` itself so the TUI works out of the box
  after `pip install caliper-ai`. No optional extra is needed.
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
