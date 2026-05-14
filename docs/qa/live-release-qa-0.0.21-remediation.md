# Caliper 0.0.21 Live Release QA - Remediation Backlog

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.21`

## Launch Readiness

Current verdict: do not call this "perfect" yet. The CLI is useful enough for
a beta launch, but the launch package has trust-breaking docs drift and enough
TUI polish gaps that a Show HN thread will focus on roughness instead of the
wedge.

Recommended launch rule:

- Ship after all "Must fix before HN" items are done.
- Keep "Should fix before broader launch" visible as known follow-ups.
- Do not market the TUI as the primary experience until navigation, themes,
  and width behavior improve.

## Must Fix Before HN

### 1. Fix docs-site budget config keys

Problem: `docs-site/src/content/docs/quickstart.mdx` uses
`daily_credits`, `weekly_credits`, and `monthly_api_dollars`. Live 0.0.21
does not treat those as budgets and exits 0 with "No budgets defined."

Fix:

- Replace the docs-site example with:

```toml
[budgets]
daily_cost_usd = 25
weekly_cost_usd = 100
monthly_cost_usd = 500
```

- Add a docs or snapshot check that rejects obsolete budget keys.

Acceptance:

```bash
caliper budgets check --config docs-example.toml --format json
```

With low thresholds, it must emit alerts and exit 2. With high thresholds, it
must emit a valid budget report and exit 0.

### 2. Align docs-site install command and sample output with README

Problem: docs-site omits `--isolated` and still shows older "credits" sample
output. README has newer install guidance and different examples.

Fix:

- Use `uvx --isolated --from caliper-ai caliper` as the docs-site first
  command.
- Update docs-site sample output to match current 0.0.21 table wording.
- Keep one source of truth for the first-run example or add a CI grep test.

Acceptance:

```bash
rg "uvx --from caliper-ai caliper|daily_credits|monthly_api_dollars|credits" docs-site
```

Should not find stale install/budget/sample-output references, except where
explicitly discussing old behavior.

### 3. Fix empty first-run onboarding for all supported vendors

Problem: a truly empty machine says it checked only Codex sessions and Codex
state DB. It does not mention Claude Code, Cursor, or Aider.

Fix:

- Include all enabled vendor roots in the empty-state "Checked" section.
- If a vendor root is missing, say whether it was absent, empty, or disabled.
- Keep paths redacted unless `--show-paths` is passed.

Acceptance:

```bash
CLAUDE_CONFIG_DIR="$tmp/claude" \
CALIPER_CURSOR_HOME="$tmp/cursor" \
CALIPER_AIDER_ROOT="$tmp/aider" \
caliper overview --session-root "$tmp/sessions" --state-db "$tmp/state.sqlite"
```

Output must mention Codex, Claude Code, Cursor, and Aider in plain language.

### 4. Round human-facing percentages and deltas

Problem: Markdown/CSV compare and what-if emit values like
`667.3694581280788` and `-21.853624423610658`.

Fix:

- Round human-facing Markdown/table percentages to 1 or 2 decimals.
- For CSV, choose either raw numeric precision by contract or a documented
  rounded percent field. Do not expose accidental float repr.
- Keep JSON raw enough for programmatic use.

Acceptance:

```bash
caliper compare --a "last 1 days" --b "previous 1 days" --format markdown
caliper whatif --days 7 --tier standard --format markdown
```

No percentage cell should contain more than two decimal places.

### 5. Reword mixed-quality evidence from fatal to proportional

Problem: one unsupported event can make the overall report say
`unsupported`, even when most rows are priced.

Fix:

- Change table/insight wording to "partial" when at least one priced event
  exists.
- Include counts: `5 priced, 1 unsupported`.
- Reserve "unsupported" for windows with no calculable or vendor-reported USD
  evidence.

Acceptance:

Use a fixture with five priced events and one unsupported event.

```bash
caliper evidence --format table
caliper insights --format markdown
```

Output should say `partial`, include the counts, and avoid implying the entire
report is worthless.

## Should Fix Before Broader Launch

### 6. Make `NO_COLOR=1` work in the TUI

Problem: `NO_COLOR=1` left `app.theme == "textual-dark"` in run-test.

Fix:

- Map monochrome fallback to an installed Textual theme such as `ansi-dark`,
  or register the bundled monochrome theme properly.
- Add a TUI test that sets `NO_COLOR=1` and asserts the resulting theme is the
  monochrome/ANSI target.

Acceptance:

```bash
NO_COLOR=1 caliper tui --demo
```

The app should visibly use the monochrome/ANSI theme, and run-test should
assert the selected theme.

### 7. Expose all shipped TUI screens through visible navigation

Problem: What-If, Budgets, Insights, and Receipt exist but are not reachable
through documented visible key bindings.

Fix:

- Add visible bindings, a command palette, or a navigation drawer/list.
- Update footer/help copy to include these screens.
- Make `?` show an actual help view rather than a transient toast.

Acceptance:

In TUI run-test, a keyboard-only user can reach Home, Intervals, Sessions,
Projects, Models, Limits, Live, Forecast, What-If, Budgets, Insights, Doctor,
and Receipt without knowing internal screen names.

### 8. Tighten 80x24 TUI layout

Problem: 80x24 screenshots wrap or clip important labels.

Fix:

- Use shorter labels or responsive layout for the three cost cards.
- Avoid splitting labels like `Last 30 days`.
- Redact or elide long diagnostic paths with a tooltip/copy action if needed.

Acceptance:

Export screenshots at 80x24 for Home, Doctor, Models, Projects, and Limits.
No title, card label, or table header should split mid-word.

### 9. Make TUI diagnostic path visibility explicit

Problem: Doctor shows absolute local paths. That is useful, but it conflicts
with the privacy posture unless clearly framed.

Fix:

- Add a visible "local paths shown for diagnostics" note on Doctor, or
  respect the same redaction toggle used elsewhere.
- In redacted mode, show basename plus status; allow explicit reveal.

Acceptance:

With default redaction on, Doctor should not display full home/temp paths
unless the user toggles reveal.

### 10. Make `statusline` compact enough for prompts

Problem: tested `statusline` output was 167 characters.

Fix:

- Add `--compact` or `--fields` to `statusline`.
- Consider defaulting text mode to a shorter line and preserving the full
  payload in JSON.

Acceptance:

```bash
caliper statusline --compact
```

Should stay under 80 characters for normal data while preserving the most
important cost/rate signal.

### 11. Reduce default multi-vendor wall-of-tables

Problem: six fixture events across three vendors produced 82 lines of
overview output.

Fix:

- Default to one unified overview table plus a short vendor summary.
- Add `--by-vendor` or `--verbose` for one-table-per-vendor output.

Acceptance:

For a three-vendor fixture, plain `caliper overview` should fit in a single
screen on 120x40. A verbose flag may print the expanded view.

### 12. Clarify `rates catalog` fresh-install behavior

Problem: fresh `rates catalog` says 0 models / no data even though embedded
rates exist.

Fix:

- Rename or label it as "live fetched pricing catalog cache."
- Print "embedded rate card available via `caliper rates show`."
- Make JSON include a `catalog_source` and `embedded_available` field.

Acceptance:

Fresh install:

```bash
caliper rates catalog
```

Should not look like pricing is missing from the product.

### 13. Suppress BrokenPipe tracebacks in Prometheus exporter

Problem: a short-timeout metrics client can cause Python `BrokenPipeError`
tracebacks on stderr.

Fix:

- Catch `BrokenPipeError`, `ConnectionResetError`, and equivalent write
  failures in the HTTP handler.
- Optionally log a one-line debug message only in verbose mode.

Acceptance:

Start `caliper export prometheus`, connect with a client that disconnects
early, and verify stderr has no traceback.

### 14. Explain why `advise` has no recommendation

Problem: the fixture showed `whatif --tier standard` reducing cost while
`advise` returned "No suggestions for this window."

Fix:

- If `advise` intentionally suppresses low-confidence or low-impact savings,
  print that threshold in the no-suggestions message.
- If `whatif` can prove a material cheaper scenario, allow `advise` to surface
  it with low/medium confidence and a short caveat.

Acceptance:

On a fixture where `whatif` reports material savings:

```bash
caliper advise --format table
```

Should either recommend the same class of change or explain why it is below
the advisor threshold.

## Can Message Around

### 15. TUI is not the primary product yet

Message it as:

> The classic CLI is the stable surface. The Textual workspace is included for
> exploration and improving quickly.

Do not lead HN with the TUI until it has complete visible navigation,
working themes, and stronger 80-column polish.

### 16. Partial pricing/evidence is inherent to local logs

Message it as:

> Caliper reports what local evidence can prove. Missing model/tier/rate data
> is surfaced as partial evidence instead of hidden.

This is a strength only if the labels are proportional and not fatal.

### 17. Prometheus extra is optional

The base install hint is good:

```text
pip install 'caliper-ai[prom]'
```

Keep this, but make launch docs mention it near exports.

## Post-Launch

### 18. Add a docs drift gate

Add a small test that scans README and docs-site for obsolete keys and install
commands:

- `daily_credits`
- `weekly_credits`
- `monthly_api_dollars`
- `uvx --from caliper-ai caliper` without `--isolated` in first-install docs
- old "credits" sample output where dollars-only output is intended

### 19. Add TUI screenshot regression tests

Keep SVG snapshots for:

- 80x24 Home, Doctor, Models, Limits
- 120x40 Home, Sessions, Projects, Forecast
- `NO_COLOR=1`
- first-run Welcome

Make the tests grep for mid-word splits and sensitive path visibility.

### 20. Add a true first-user smoke script

Create a release smoke script that installs from PyPI into a temp home and
runs:

- `caliper --version`
- empty `caliper overview`
- fixture `overview`, `doctor`, `evidence`, `budgets check`
- `caliper tui --demo` via Textual run-test
- JSON/CSV parse checks

This catches docs/release drift better than unit tests alone.

### 21. Make exports feel like one family

Document which exporters need usage data and which emit static templates.
Either accept common source flags everywhere or clearly reject them with a
short explanation.

## Won't Fix / Intentional Tradeoffs

### 22. Local-first over hosted dashboard

Keep this. It is the strongest positioning choice.

### 23. No telemetry

Keep this. The privacy claim depends on it.

### 24. CLI first, TUI second

Acceptable for 0.x, but only if the launch copy does not imply the TUI is as
mature as the CLI.

## Final Acceptance Checklist For HN

- `uvx --isolated --refresh --from caliper-ai caliper --version` prints the
  latest PyPI version.
- README and docs-site install commands match.
- Docs-site budget example actually creates budgets.
- Empty first-run mentions all supported vendors.
- JSON redaction test still passes.
- No prompt/title fixture marker leaks in stdout.
- Human Markdown output has rounded percentages.
- TUI `NO_COLOR=1` selects the expected monochrome/ANSI theme.
- TUI 80x24 screenshots do not split key labels mid-word.
- TUI help/navigation exposes every marketed screen.
- `rates catalog` explains fresh-install cache state clearly.
- Prometheus exporter suppresses disconnect tracebacks.

## Implementation Pass Status

Completed in this remediation pass:

- Items 1 through 21 now have code, documentation, or test coverage in the
  working tree. Items 22 through 24 are intentional positioning tradeoffs and
  are documented rather than changed.
- TUI launch-hardening tests cover demo mode, `NO_COLOR`, shortcut navigation,
  80x24/120x40 screenshot regressions, first-run Welcome, and default Doctor
  redaction/reveal behavior.
- CLI tests cover docs drift, empty overview vendor messaging, rounded
  percentage exports, git attribution evidence handling, compact statusline,
  fresh-install pricing catalog messaging, proportional priced/unsupported
  evidence, and Prometheus client disconnects.

Verification completed:

```bash
uv run pytest tests/test_evidence.py tests/test_insights.py tests/test_statusline.py tests/test_prom_export.py tests/test_cli_helpers.py tests/test_commands.py tests/test_docs_drift.py tests/tui/test_launch_hardening.py
uv run pytest
scripts/release-smoke.sh
CALIPER_SMOKE_PACKAGE=. scripts/live-release-smoke.sh
```

Remaining before claiming a live release:

- Run `scripts/live-release-smoke.sh` against the intended PyPI version after
  publishing, for example `CALIPER_SMOKE_VERSION=0.0.22 scripts/live-release-smoke.sh`.
- Re-run the actual package from PyPI with
  `uvx --isolated --refresh --from caliper-ai caliper --version`.
