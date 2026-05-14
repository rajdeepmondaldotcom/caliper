# Caliper 0.0.22 Final Live Release QA - Remediation Backlog

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.22`

## Launch Readiness

Current verdict: ship as a beta after launch-copy cleanup. Do not describe the
UI/UX as perfect.

The core package is healthy: installs work, tests pass, live smoke passes,
multi-vendor fixtures work, privacy redaction held, and the TUI no longer has
the obvious 0.0.21 launch blockers.

The highest-leverage fixes are now presentation and trust fixes. Prioritize
what a hostile public reader will screenshot: launch copy, default human
tables, visible paths, and unsupported pricing display.

## Must Fix Before HN

### 1. Update all launch drafts to the live install command and current output language

Problem: `docs/launch/*` still uses:

```bash
uvx --from caliper-ai caliper
```

The README and PyPI recommend:

```bash
uvx --isolated --from caliper-ai caliper
```

`docs/launch/hn-show.md` also still shows old `credits` sample output.

Fix:

- Replace launch draft install commands with
  `uvx --isolated --from caliper-ai caliper`.
- Remove `credits` from the Show HN sample and use current table wording.
- Update the launch checklist in `docs/launch/README.md`.
- Add a grep-style check that fails on stale launch-copy patterns.

Acceptance:

```bash
rg "uvx --from caliper-ai caliper|daily_credits|weekly_credits|monthly_api_dollars|credits" README.md docs/launch CHANGELOG.md pyproject.toml
```

Expected: no stale launch-command hits in `docs/launch/*`, and no old
credits-based sample output except historical changelog context.

### 2. Make 80-column report tables readable by default

Problem: `caliper project --width 80` and `--compact` still split high-value
labels mid-word: `gpt-5.\n5`, `Anthro\npic`, `unknow\nn`.

Fix:

- Add an automatic narrow-table mode for terminal widths under 100 columns.
- In narrow mode, prefer fewer columns over wrapped labels.
- Collapse `Reported $` / `Calc $` into a single evidence marker or hide them
  behind `--wide`.
- Shorten model/provider labels with deterministic ellipses rather than
  mid-word wrapping.
- Print long source paths as `~/.../sessions` or `<redacted-path>` by default.

Acceptance:

```bash
caliper project --width 80
caliper project --width 80 --compact
caliper overview --width 80
caliper models --width 80
```

Expected: no model, provider, status, or column header splits mid-word. The
first screen should look intentionally compact, not broken.

### 3. Make unsupported pricing visually distinct from zero cost

Problem: an unsupported or unknown-priced model can appear as `$0` in human
tables while warnings above the table carry the real explanation.

Fix:

- Render unsupported calculated cost as `unsupported`, `n/a`, or `-`, not
  `$0`.
- Preserve true vendor-reported `$0` as `$0` only when the source actually
  reported zero.
- Add a row-level pricing evidence marker for partial/unsupported rows.
- Keep totals conservative and explain priced vs unsupported counts.

Acceptance:

Use a fixture with priced Codex, vendor-reported Aider, and unknown Cursor.

```bash
caliper project --format table
caliper overview --format table
caliper evidence --format table
```

Expected: the unknown Cursor cost is impossible to mistake for a real zero.

## Should Fix Before Broader Launch

### 4. Redact or shorten local roots in default human output

Problem: default table output prints the absolute session root. JSON redaction
is correct, but screenshots can still reveal local usernames or temp paths.

Fix:

- Default human source paths to `~`-relative or `<redacted-path>`.
- Add `--show-paths` parity for human output if the user wants full paths.
- Keep `doctor` useful by showing enough basename/status detail for debugging.

Acceptance:

```bash
caliper overview
caliper project
caliper doctor
caliper overview --show-paths
```

Expected: default output does not reveal absolute home/temp roots; explicit
`--show-paths` does.

### 5. Give `rates catalog` a usable first-run shape

Problem: `caliper rates catalog` can print nearly two thousand rows and heavy
numeric precision. It works, but it overwhelms the terminal.

Fix:

- Add `--provider`, `--model`, `--search`, `--top`, or `--limit`.
- Default table output to a provider summary plus next commands, or cap rows.
- Keep full catalog available through JSON or an explicit `--all`.

Acceptance:

```bash
caliper rates catalog
caliper rates catalog --provider openai
caliper rates catalog --model gpt-5.5
caliper rates catalog --format json
```

Expected: default table output is scan-friendly; full JSON remains available.

### 6. Polish Markdown numeric formatting for human reports

Problem: Markdown compare/what-if output is valid but raw-looking:
`0.3206750`, `-0.0500000`, and `-15.59` without `$` or `%`.

Fix:

- Format money as `$0.32` style in Markdown.
- Format percentages with `%`.
- Keep JSON exact fields unchanged.
- If CSV stays raw by contract, document that CSV is machine-oriented.

Acceptance:

```bash
caliper compare --comparison-window-a "last 7 days" --comparison-window-b "previous 7 days" --format markdown
caliper whatif --scenario-history-days 7 --hypothetical-service-tier fast --format markdown
```

Expected: Markdown is pasteable into a finance or launch note without manual
cleanup.

### 7. Clarify or harmonize `overview` window flags

Problem: most report commands accept `--days` / `--lookback-days`.
`overview` rejects them because it is a fixed 7/30/90 rollup.

Fix:

- Either make `overview --help` explicitly say it is fixed-window and not
  scopeable, or accept a scoping anchor flag while preserving the 7/30/90
  shape.
- Add a regression test for the chosen behavior.

Acceptance:

```bash
caliper overview --help
caliper overview --days 7
```

Expected: either the command works or the error/help makes the fixed-window
choice obvious.

### 8. Clarify budget period semantics

Problem: `budgets check` daily/weekly/monthly windows are calendar-ish, not
always "last 24h." In the QA fixture, weekly/monthly breached while daily was
OK because the event was roughly one day old.

Fix:

- Add one sentence to `budgets check --help` and README explaining the period
  windows.
- Consider JSON metadata that names each budget window start/end.

Acceptance:

```bash
caliper budgets check --format json
caliper budgets check --help
```

Expected: users can tell exactly what daily, weekly, and monthly mean.

## Keep Green

Do not regress these verified 0.0.22 behaviors:

- `uvx --isolated --refresh --from caliper-ai==0.0.22 caliper --version`
  resolves the published package.
- `pipx run --spec caliper-ai==0.0.22 caliper --version` works.
- Fresh venv `pip install caliper-ai==0.0.22` works.
- `uv run pytest` remains green.
- `scripts/live-release-smoke.sh` passes with `CALIPER_SMOKE_VERSION=0.0.22`.
- `scripts/release-smoke.sh` passes.
- Empty overview names Aider, Claude Code, Cursor, and OpenAI Codex.
- JSON redaction hides absolute paths, prompts, and private titles by default.
- `--show-paths` reveals paths intentionally.
- Malformed config exits 2 without traceback.
- TUI shortcut navigation reaches every shipped secondary screen.
- `NO_COLOR=1` selects `monochrome`.

## Suggested Order

1. Fix `docs/launch/*` stale launch copy.
2. Make unsupported pricing distinct from real zero.
3. Fix 80-column table wrapping.
4. Redact or shorten human source paths.
5. Polish Markdown money/percent formatting.
6. Add rates catalog filtering/summary.
7. Clarify `overview` and budget window semantics.
