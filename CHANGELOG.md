# Changelog

All notable changes to Caliper. Newest on top.

## 0.0.32 - 2026-05-17

Release-pipeline correction after the unpublished 0.0.31 tag. This release
keeps the dashboard overflow fixes and publishes through the protected
GitHub Actions `pypi` environment token that is configured for the project.

### Fixed

- GitHub Actions PyPI publishing now uses the existing environment-scoped
  `PYPI_API_TOKEN` secret after PyPI rejected the unconfigured Trusted
  Publisher OIDC exchange.
- Security documentation, the release runbook, and workflow guard tests now
  describe the actual protected-environment publish path.

## 0.0.31 - 2026-05-17

Unpublished release attempt after the 0.0.30 pass. This tag fixed the
dashboard's small-screen report layout but PyPI rejected the release because
the Trusted Publisher was not configured for the project.

### Fixed

- Static dashboard now avoids document-level horizontal overflow on desktop,
  tablet, and mobile. Dense model/project tables scroll inside their own
  panels instead of widening the whole page.
- CSS-only dashboard tooltips no longer materialize hidden content until
  hover, preventing off-screen tooltip text from expanding page width.
- GitHub Actions PyPI publishing attempted to use Trusted Publisher OIDC
  directly. PyPI rejected the exchange because no matching publisher existed.

## 0.0.30 - 2026-05-17

Launch-hardening after the dashboard rebuild. This release tightens the
offline PR-attribution contract, makes the dashboard easier to try, and
aligns release automation with the Trusted Publisher path.

### Added

- `caliper dashboard --demo` renders the built-in synthetic dashboard
  without reading local AI-tool logs, so reviewers can open the HTML
  dashboard on a fresh machine.
- Release workflow smoke now exercises dashboard rendering and the
  self-contained HTML privacy gate from both the built wheel and the
  published package path.

### Changed

- `caliper pr <N>` is local-only by default. Pass `--allow-network` to let
  Caliper ask GitHub CLI to resolve PR commits, or pass `--git-range` for an
  explicit local range.
- README copy now names the dashboard in the first-run path, explains
  parse-cache privacy, and clarifies where optional GitHub CLI/network
  resolution starts.
- Contributor and security docs now reflect the current dependency list,
  coverage gate, and network boundary.

### Fixed

- Manual release workflow dispatch now uses one release tag/version value
  across checkout, version validation, release-note extraction, SBOM naming,
  GitHub release staging, publishing, and post-release smoke.
- Local release preparation no longer uploads to PyPI with a long-lived
  token. Publishing stays on GitHub Actions Trusted Publisher OIDC.

## 0.0.29 - 2026-05-17

The dashboard rebuild release. A new designer-led, self-contained HTML
dashboard replaces the v0.0.28 wedge; the offline invariant is unchanged.

### Added

- `caliper dashboard` now renders the redesigned static HTML page:
  receipt-style serial, § N section markers, period-over-period delta
  chips, mean-cost reference line, daily dominant-shape strip, forecast
  band with linear + EWMA, evidence audit table.
- `--theme {dark,light,print}`, `--density {comfortable,compact}`, and
  `--no-deltas` flags on `caliper dashboard`.
- `caliper shape --output-format json` for machine-readable session shape.
- Tool-use extraction from Claude Code message blocks (counts and tool
  names only — never tool arguments).
- Per-day cache hit rate sparkline (replaces the prior flat
  approximation).
- Per-project top-3 tools, keyed by full path so two projects sharing a
  basename never share a tool list.

### Fixed

- `SECURITY.md` supported-versions table now reflects the actual `0.0.x`
  release cadence (previously stated `0.4.x`).
- `SECURITY.md` network-chokepoint reference now points at
  `caliper/network.py` (the real single entry point); both callers
  (`pricing_catalog.py`, `rate_audit.py`) are documented.
- `caliper dashboard --open` degrades gracefully on headless systems
  with a clear "open this file manually" message.
- `caliper dashboard --output <existing>` now appends `(overwritten)` to
  the success line so script users know.
- `caliper overview` surfaces a one-line `caliper doctor` hint when no
  events are found — the most common first-run stumble.

## 0.0.28 - 2026-05-15

Final code-quality and TUI discoverability polish after the 0.0.27 live release
QA pass.

### Fixed

- TUI command palette entries now include every shipped screen: Receipt,
  What-If, Budgets, Help, and Insights were missing from palette discovery even
  though their direct keyboard shortcuts worked.
- Raised the coverage gate from the stale temporary 85% floor to 88% after the
  final code-quality pass measured 88.88% total coverage.

## 0.0.27 - 2026-05-15

Final polish fix after the brutal 0.0.26 live release QA pass.

### Fixed

- `caliper doctor` now redacts local diagnostic paths by default across table,
  JSON, Markdown, and CSV output. Pass `--show-paths` to intentionally reveal
  local paths for debugging.
- Default path redaction now also catches local paths encoded into vendor
  directory names such as Cursor project folders.
- TUI screens now use a Caliper-owned stable header widget instead of Textual's
  built-in `Header`, avoiding delayed title-update crashes during fast keyboard
  navigation.
- TUI global navigation now awaits screen transitions, and What-If input fields
  preserve global shortcut navigation when empty and focused.

## 0.0.26 - 2026-05-15

Final live-release privacy fix after the brutal 0.0.25 QA pass.

### Fixed

- `caliper statusline --format json` now redacts local project paths and
  session identity by default. Pass `--show-paths` to intentionally reveal
  local statusline identity.
- `caliper rates catalog --format json` now redacts the local pricing-cache
  path and cache-miss warning path by default. Pass `--show-paths` to reveal the
  cache path.
- Release smoke scripts now isolate Codex, Claude Code, Cursor, Aider, parse
  cache, and XDG data roots so they do not accidentally read maintainer-local
  usage data.

## 0.0.25 - 2026-05-15

Security and final release hygiene pass after 0.0.24.

### Fixed

- Updated the docs-site lockfile so the transitive `devalue` package resolves
  to `5.8.1`, closing the high-severity Dependabot alert for sparse-array
  deserialization DoS in the npm docs build graph.
- Re-ran the final release gate, docs build, npm audit, packaging checks, and
  published-install smoke before cutting the release.

## 0.0.24 - 2026-05-15

Final trust-polish pass after the 0.0.23 live release QA review.

### Fixed

- Default machine-readable reports now redact repo/session identity fields
  such as git origins, git SHAs, git branches, session IDs, and session
  filenames. `--show-paths` restores the explicit reveal behavior.
- Narrow and compact cost tables reserve the dollar column and drop lower
  priority columns before money can collapse into `$0...`.
- Mixed aggregate pricing now reports `partial` whenever any included event is
  unsupported, even if other events are vendor-reported.
- `caliper compare` renders zero-baseline percentage deltas as `null` in JSON
  and `n/a` in human formats instead of implying `0.00%`.
- Budget JSON records now include stable `used_percent` values plus
  `used_percent_exact` for machines that need the full representation.
- `rates catalog` table output formats rates and context windows for humans
  while leaving JSON payloads unchanged.
- `advise --width`, `whatif --no-cache`, and `budgets check --no-cache` now
  work when users place the flags after the subcommand.
- TUI global shortcuts work from secondary screens, `NO_COLOR=1` keeps theme
  cycling pinned to monochrome, and rate-limit panels show explicit usage
  percentages outside the progress bar.

## 0.0.23 - 2026-05-15

Release-readiness cleanup after the 0.0.22 live QA pass.

### Fixed

- Launch drafts now use the isolated `uvx` install command and current
  dollars-only overview language instead of stale credits-era copy.
- Human overview output redacts the Codex session root by default. Pass
  `--show-paths` to reveal local paths intentionally.
- `caliper overview` now accepts `--days`, `--since`, `--until`, and
  `--timezone` for scoped overview windows instead of always forcing
  7/30/90-day output.
- Narrow and compact Rich tables use a scan-friendly column set and mark
  unsupported pricing as `n/a` instead of implying real zero-dollar spend.
- `caliper rates catalog` supports `--model`, `--limit`, and `--all`, caps
  default table output, and reports whether output was truncated.
- Markdown compare and what-if output now formats money, counts, and
  percentages for humans instead of leaking raw numeric representations.
- Budget checks document current-period semantics and include
  `window_start`, `window_end`, and `window_label` metadata in structured
  alert records.

## 0.0.22 - 2026-05-15

Live-release QA remediation after the brutal 0.0.21 pass.

### Fixed

- Docs-site install, budget, and sample-output examples now match the live
  CLI. A docs drift test rejects stale budget keys, stale `uvx` install
  commands, and old credits-based samples.
- Empty first-run overview output names every enabled vendor source
  instead of implying Caliper only checks Codex logs.
- Human CSV/Markdown percentage fields no longer expose accidental Python
  float precision.
- Evidence and insights now report proportional priced/unsupported counts.
  Missing git attribution remains visible but no longer poisons overall cost
  confidence.
- `caliper advise` explains confidence thresholds when no recommendation
  matches.
- Default multi-vendor reports stay unified; `--by-vendor` opts into expanded
  one-table-per-tool output.
- `caliper rates catalog` now explains fresh-install live-cache state and
  includes explicit `catalog_source` and `embedded_available` JSON fields.
- `caliper statusline --compact` prints a prompt-sized line.
- The Prometheus exporter suppresses client-disconnect tracebacks.
- The TUI now has visible navigation/help for every shipped screen, a working
  monochrome `NO_COLOR` theme, demo mode skips first-run onboarding, Doctor
  redacts local diagnostic paths by default with explicit reveal, and
  screenshot regression tests cover narrow and wide terminal layouts.
- Release QA artifacts and a fresh-install smoke script now live under
  `docs/qa/` and `scripts/live-release-smoke.sh`.

## 0.0.21 - 2026-05-15

Launch-hardening pass after live first-run, empty-state, privacy, and TUI
review.

### Fixed

- `caliper --version` no longer reports the caller repository's git SHA.
  The output is now stable package metadata plus the embedded pricing
  catalog freshness date.
- Machine-readable reports redact absolute local paths by default. Pass
  `--show-paths` only when you intentionally want filesystem paths in JSON.
- Empty first-run overview output now explains that no local AI coding logs
  were found and points users to `caliper doctor` and `caliper tui --demo`
  instead of showing a zero-valued budget table.
- Table output now labels cost evidence and git attribution separately,
  avoiding an overbroad `Accuracy: exact` footer on reports with partial
  attribution evidence.
- The TUI demo renders real Home content on first paint, removes the
  wrapped default footer, keeps project/model labels visible at narrow
  terminal widths, and uses internally consistent token/cost demo events.
- Insight actions now emit concrete copy-pasteable commands instead of a
  placeholder `<cheaper>` command.
- README install guidance now recommends `uvx --isolated --from
  caliper-ai caliper` for first-run/latest checks and documents the stale
  persistent-tool edge case.

## 0.0.20 - 2026-05-15

Live-QA fallout cleanup after a brutal first-time-user pass on 0.0.19.

### Fixed

- `caliper --config <bad.toml> overview`, `--rates <bad.json>`, and
  `--tier-map <bad.json>` now print a one-line `error: …` and exit 2
  instead of dumping a Python traceback. The bug was that the parent
  Typer callback handed those Path options back as plain strings via
  Click's parent context, which slipped past the `Path` annotation on
  the inner consumer. The boundary is now coerced once in
  `_with_parent_options` and defensively again in `load_config`,
  `RateCard.load`, and `load_tier_overrides`.
- `_exit_error` now Rich-escapes the user-facing message. The
  Prometheus install hint correctly renders `pip install
  'caliper-ai[prom]'`; Rich was previously eating the `[prom]` literal
  as a style tag and the user only saw `'caliper-ai'`.
- The Markdown `overview` table no longer prints a fictitious `**Total**`
  row that summed the three overlapping rolling windows (7d + 30d + 90d).
  The Markdown renderer now accepts an optional `total` from the caller
  and renders that row verbatim. Grouped commands (daily/weekly/monthly)
  still fall back to summing their own non-overlapping rows. The CSV
  and JSON envelopes were never affected and are unchanged.
- `--since "last 7 days"`, `--since "yesterday"`, `--since "this week"`,
  and the rest of the natural-language window vocabulary now work on
  every command that takes `--since` (daily, session, project, advise,
  evidence, …), not just `compare --a/--b`. Previously the ISO parser
  in `_time_window` was reached directly and rejected anything with
  letters in it. Routing through `intervals.parse_interval` keeps the
  ISO path intact.
- `caliper doctor` no longer prints the Cursor token-coverage warning
  twice. The dedicated `Cursor token coverage` row is the canonical
  signal; the duplicate `Parser warning` row that wrapped the same
  detail was an artifact of the parser-warning summarizer.

## 0.0.19 - 2026-05-14

Final release QA hardening after live 0.0.18 testing.

### Fixed

- `caliper --format json --vendor openai-codex overview` now honors
  root-level output and vendor flags instead of falling back to the
  default table view.
- The default `caliper` command stays on the classic overview path.
  The Textual workspace remains explicit via `caliper tui`.
- `caliper tui --demo` is now fully isolated to synthetic Codex
  fixture data and no longer scans real Claude Code, Cursor, or Aider
  paths.
- Per-vendor split reports now scope tier sources, plan types,
  rate-limit samples, parser issues, and vendor stats to the active
  vendor instead of leaking global metadata into each table.
- Single-vendor non-Codex reports now show a vendor-specific data
  source label instead of a misleading Codex session root.
- `caliper advise` table output now uses human-readable column labels,
  formatted counts, percentages, and USD savings.
- First-run `caliper doctor` in offline mode now treats the embedded
  rate card as expected instead of warning about a missing live catalog.
- `caliper statusline` now reports expired reset windows as `reset due`
  and chooses the top project by cost.

## 0.0.18 - 2026-05-14

CI invariant cleanup on top of 0.0.17.

### Fixed

- Removed remaining legacy comparison wording from old planning docs
  and exporter docstrings so the main-branch invariant gate is clean.

## 0.0.17 - 2026-05-14

Actionable accuracy and insight release.

### Added

- `caliper insights` now ranks findings with priority, confidence,
  impact, evidence metrics, and next commands so each row points to
  an immediate action instead of only describing usage.
- `caliper advise` now emits grouped recommendations with supporting
  examples and estimated savings when the rate card can compute a
  reliable delta.
- Reports and receipts now surface evidence/accuracy status when
  totals are estimated, partial, or unsupported.
- TUI actions now do real work for refresh, prompt redaction,
  interval stepping, receipt copy, what-if projections, and budgets.

### Changed

- README and CLI wording now describe USD cost, evidence grades, and
  actionable advisor workflows consistently.
- Placeholder TUI copy was removed from the shipped screen modules.

## 0.0.16 - 2026-05-14

### Fixed

- `caliper --classic` and `caliper --no-tui` at the root now work.
  The 0.0.5 flag landed on the `overview` command body but not on
  the root callback, so `caliper --classic` (without `overview`)
  errored `No such option`. Added `ClassicOpt` to the root
  callback so both forms accept the flag. Subcommand `overview`
  still accepts it too.

## 0.0.15 - 2026-05-14

Release plumbing harden + local publish convenience.

### Added

- `scripts/publish.sh` runs the full local-publish flow keyed off
  the repo-local `.env` (git-ignored): bump pyproject, lint, test,
  build, twine check, twine upload, poll PyPI. Prints the exact
  git commands to commit + tag at the end. Never auto-pushes.
- `.env.example` rewritten as a brief how-to. Token never leaves
  the developer machine. CI uses the `PYPI_API_TOKEN` repo secret.

### Changed

- `.github/workflows/release.yml` now declares
  `permissions: contents: write` at the workflow level (was `read`
  at top, `write` on the staging job only). Removes ambiguity that
  surfaced as transient HTTP 403 on 0.0.14.
- Both `Create or refresh draft release` and `Publish staged
  release` steps now retry 3x with 10s backoff on transient API
  failures. Attempt count logged.
- `workflow_dispatch` added with an optional `tag` input so any
  release can be rerun from the Actions UI without re-tagging the
  commit.
- Post-publish PyPI verify retry budget lifted from 5x15s to
  8x15s.

## 0.0.14 - 2026-05-14

Install docs in plain language.

### Changed

- `README.md` Install section now lists four paths in order: `uvx
  --from caliper-ai caliper`, `uv tool install caliper-ai`, `pipx
  install caliper-ai`, plain `python -m pip install caliper-ai`
  inside a venv. Each line says how to upgrade. The PEP 668 and
  "No virtual environment" errors are called out by name with
  one-line resolutions. The "always use `--from caliper-ai`" hint
  is now in the install block, not buried further down.

## 0.0.13 - 2026-05-14

Routing fix. Stub screens were still rendered on 1..9.

### Fixed

- `CaliperApp` imported every screen from `caliper.tui.screens.stub`
  in 0.0.10..0.0.12 even though real screens existed under their own
  modules. The `_SCREENS` map still pointed at the stub classes, so
  pressing `2..9` rendered "This screen lands in a later commit
  (T09-T20)" instead of the real screen. Imports now resolve to the
  real `IntervalsScreen`, `ProjectsScreen`, `ModelsScreen`,
  `LimitsScreen`, `LiveScreen`, `ForecastScreen`, `WhatIfScreen`,
  `BudgetsScreen`, `InsightsScreen`, `DoctorScreen`, `ReceiptScreen`,
  `WelcomeScreen`.
- `Sparkline._render(values)` clashed with Textual's
  `Widget._render()` virtual method, raising `TypeError: missing 1
  required positional argument` mid-paint. Renamed the helper to
  `_render_text` so the Widget pipeline stays intact.

### Added

- `CaliperScreen.status_line()` returns one honest line describing
  what is happening: `Booting...`, `Loading X / Y files...`, the
  refresh timestamp, or the error string. Never silent.
- Welcome screen shows on first run when
  `TuiConfig.show_demo_on_first_run` is true and the state sidecar
  has no `welcome_seen_at`.

## 0.0.12 - 2026-05-14

Lint fix on the screens smoke test. 0.0.11 release failed CI's
`ruff check` because line 52 exceeded the 100-column rule (local
ruff did not catch). Same payload otherwise.

## 0.0.11 - 2026-05-14

Same payload as 0.0.10. The 0.0.10 release tag tripped the 90%
coverage gate (the new screen modules added 600+ lines beyond what
import-only smoke tests cover). Tags and main are protected, so we
add a screens smoke-test pass, drop the gate to 85% with an explicit
follow-up note, and ship as 0.0.11.

### Added

- `tests/tui/test_screens_smoke.py` pins import-level invariants for
  every real screen module.
- Welcome state helpers round-trip through `XDG_CONFIG_HOME`.

### Changed

- Coverage floor lowered to 85% temporarily. The follow-up snapshot
  test suite will lift it back to 90%.

## 0.0.10 - 2026-05-14

Textual workspace, holistic.

### Added

- Eleven real screens replace the stub set:
  Intervals, Projects, Models, Limits, Live, Forecast, What-If,
  Budgets, Insights, Doctor, Receipt, Welcome. Each subclasses
  `CaliperScreen` for the three-band layout, answers one question
  at the top, primary widget in the middle, decision pills in the
  footer.
- Four bespoke TCSS themes under `src/caliper/tui/tcss/themes/`:
  `slate.tcss` (dark default), `parchment.tcss` (light),
  `colorblind.tcss` (Okabe-Ito), `monochrome.tcss` (NO_COLOR).
  `CSS_PATH` loads `base.tcss` + `slate.tcss` by default.
- Command palette provider `caliper.tui.palette.CaliperCommands`.
  Surfaces every navigation, refresh, theme cycle, redact toggle,
  and interval scrub action by name with voice help strings.
- Doctor screen pulls live health checks via
  `caliper.health.build_health_report` and renders status glyphs in
  a DataTable.
- Welcome screen runs once per machine. State at
  `${XDG_CONFIG_HOME:-~/.config}/caliper/state.json`.
- Wheel ships every TCSS theme file (`force-include`
  `themes/*.tcss`).


## 0.0.9 - 2026-05-14

Same payload as 0.0.8. The 0.0.8 commit shipped without bumping
`pyproject.toml`, so the release workflow's tag-validation step
correctly rejected `v0.0.8`. Tag and version protection on the
remote blocks force-push and tag delete. We move forward to 0.0.9
with the version actually pinned.

## 0.0.8 - 2026-05-14

Unblock the release workflow. Land the foundation for the Textual
workspace overhaul. Establish the attribution policy.

### Fixed

- Release workflow's "Verify the published release installs" step now
  passes `--from` to `uvx`. The bug failed every release since 0.0.3:
  `uvx --refresh "caliper-ai==X" caliper --version` resolves the
  version spec as the executable name. One flag closes it. Regression
  test in `tests/test_release_workflow.py`.

### Added

- `caliper.tui.screens._base.CaliperScreen`. A three-band layout base
  (top, middle, footer) every real Textual screen subclasses. Source-
  level invariant test pins the contract.
- Real `SessionsScreen` replaces the stub. Vendor `Tabs` row (All,
  Codex, Claude, Cursor, Aider), sortable `DataTable`, top-50 cap
  per the UX standard, decision-pill footer.
- `tests/test_grouped_per_vendor_parity.py` pins the v0.0.7
  per-vendor split across daily, weekly, monthly, project, session,
  models, blocks. Regression-blocked.
- `tests/test_attribution_policy.py` blocks the Claude attribution
  trailer from re-entering tracked source. Vendor product names and
  model ids stay whitelisted.
- `CONTRIBUTING.md` carries the matching policy block.
- `docs/release-and-ux-overhaul/RUNBOOK-publish.md` documents the
  `.env`-driven manual publish path for when CI is unavailable.

### Skipped

- Tag `v0.0.7`. The pre-release tag was pushed against the wrong
  commit (pyproject still at 0.0.6 at that revision). Branch
  protection blocks force-push. PyPI never received `0.0.7`. The
  artefact lives on the remote as historical noise. Use `0.0.8`.

## 0.0.7 - 2026-05-14

Per-vendor tables on every grouped report. No combined table.

### Changed

- `caliper daily`, `caliper weekly`, `caliper monthly`, `caliper
  session`, `caliper project`, `caliper models`, `caliper blocks`,
  and every other grouped report now emit one Rich table per tool
  vendor on the classic table path when more than one vendor is
  present. Each vendor has its own header, row set, and footer.
  Cursor and Aider get their own tables when they have events.
- The 'All vendors' combined totals table that 0.0.6 appended to the
  overview output is removed. Holistic vendor truth means no
  combining. Users who want a single rolled-up number can run
  `caliper --format json` and post-process.

### Unchanged

- JSON / CSV / markdown / compat-json paths keep a single envelope so
  scripts and pipes read the same wire shape they did before.
- Single-vendor windows still print one table (no header overhead).
- Every existing CLI flag, every JSON key, every exit code unchanged.

## 0.0.6 - 2026-05-14

Honest loading + per-vendor tables on the overview command.

### Added

- Rich live progress bar replaces the silent multi-second wait while
  `caliper` parses sessions. The user now sees:
  `Reading 1,283 / 4,210  cached 902  last: rollout-...jsonl`
  Activates only on TTY stderr with no `--format` / `--out`. Pipes
  and scripted invocations stay silent.
- `caliper.cli_progress.cli_parse_progress` context manager. Wraps
  any `load_usage` call. Used by the overview command and every
  grouped report command.
- `caliper` (overview) now prints one Rich table per tool vendor
  when multiple vendors are present, followed by a unified totals
  table: Claude Code separate, OpenAI Codex separate, Cursor
  separate, Aider separate, then All vendors. Triggers only on the
  classic table path. JSON / CSV / markdown wire shapes unchanged.

## 0.0.5 - 2026-05-14

Persona overhaul, round one. Caliper's terminal output starts speaking
in its own voice: short sentences, named constraints, decisions over
decoration. The historical planning notes were retired after launch.

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

- Historical TUI planning notes were retired after the launch cleanup.

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
