# Caliper 0.0.23 Final Live Release QA - Remediation Backlog

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.23`

## Launch Readiness

Current verdict: ship as a serious public beta / Show HN if needed. Do not call
the UI/UX perfect.

0.0.23 has no P0 launch blocker from this pass. The release is live on PyPI,
install checks pass, full tests pass, release smoke passes, launch copy is no
longer stale, empty states are useful, and the main privacy/path defaults are
much better.

The fixes below are about trust polish. They should be done before claiming the
tool is launch-perfect.

## Must Fix Before Calling It Perfect

### 1. Redact repo/session identifiers in default JSON or document the boundary

Problem: default JSON redacts prompts, titles, and absolute paths, but still
exposes repo/session identifiers such as:

```text
2026-05-15T04-00-00-private-acquisition
git@github.com:stealth/private-acquisition.git
```

Fix:

- Prefer redacting git origin URLs and session file stems by default in JSON.
- Add explicit reveal behavior, for example `--show-repos` or fold it into
  `--show-paths` if that is the intended trust boundary.
- If repo names are intentionally part of default output, document that clearly
  in README, docs-site concepts, and schema notes.

Acceptance:

```bash
caliper overview --format json
caliper project --format json
caliper overview --format json --show-paths
```

Expected: default JSON does not reveal private prompt text, titles, absolute
paths, git origin URLs, or session filename stems. Explicit reveal flags restore
the intended fields.

### 2. Never truncate the dollar cell in narrow tables

Problem: `caliper project --width 80` can still show the cost as `$0...`.

Fix:

- In narrow mode, reserve enough width for the formatted cost.
- Drop or further compress less-critical columns before truncating money.
- Consider a stacked row layout for `--width < 90`.

Acceptance:

```bash
caliper project --width 80
caliper project --width 80 --compact
caliper session --width 80
caliper models --width 80
```

Expected: every row shows a readable cost value such as `$0.84`, `n/a`, or
`unsupported`; no row shows `$0...`.

### 3. Use `partial` or `mixed` for aggregates with unsupported pricing

Problem: row-level unsupported pricing is now visible as `n/a`, but some mixed
aggregate rows still show `vendor-reported` when the evidence table says the
overall pricing status is partial.

Fix:

- For aggregate pricing labels, choose the least-confident applicable status.
- If an aggregate contains any unsupported pricing, label it `partial` or
  `mixed`.
- Keep vendor-reported as a row/aggregate label only when all included cost is
  genuinely vendor-reported and no unsupported cost is present.

Acceptance:

Use a fixture with priced Codex, priced Claude Code, vendor-reported Aider, and
unknown-priced Cursor.

```bash
caliper overview --width 80
caliper project --width 80
caliper models --width 80
caliper evidence
```

Expected: table pricing labels and evidence labels tell the same story.

### 4. Fix compare percentage semantics when the baseline is zero

Problem: Markdown compare can report a nonzero increase from zero as `0.00%`.

Fix:

- When baseline is zero and current is nonzero, render percentage as `n/a`,
  `new`, or another explicit non-finite state.
- Apply the same rule to table, Markdown, CSV if user-facing, and JSON metadata.
- Preserve exact numeric fields where needed for machines.

Acceptance:

```bash
caliper compare --comparison-window-a "last 1 day" --comparison-window-b "previous 1 day" --format markdown
caliper compare --comparison-window-a "last 1 day" --comparison-window-b "previous 1 day" --format table
```

Expected: cost/tokens/events with a zero baseline never show `0.00%` for a
nonzero delta.

## Should Fix Before Broader Launch

### 5. Normalize common option placement across commands

Problem: users can reasonably write `caliper advise ... --width 100`, but the
command rejects `--width` unless it is placed before the subcommand.

Fix:

- Decide which options are root-only and which are command options.
- Where possible, allow common report flags after the subcommand for every
  report command.
- At minimum, make help text and examples consistently use the supported order.

Acceptance:

```bash
caliper --width 100 advise
caliper advise --width 100
caliper --no-cache whatif --scenario-history-days 7
caliper whatif --no-cache --scenario-history-days 7
```

Expected: either both forms work for common report flags, or rejected forms have
clear help and no docs/examples use them.

### 6. Quantize budget percentages in JSON

Problem: `budgets check --format json` can emit raw float precision such as:

```json
"used_percent": 8333.333333333334
```

Fix:

- Add `used_percent_exact` as a string, or quantize `used_percent` to a stable
  decimal precision.
- Keep money exact fields unchanged.

Acceptance:

```bash
caliper budgets check --format json
```

Expected: percentage values are stable and intentional, not Python float noise.

### 7. Polish `rates catalog` numeric formatting

Problem: `rates catalog` is now capped and filterable, but table values still
look raw: `3.000000`, `0.5000000`, `15.000000`.

Fix:

- Format table money rates with human precision.
- Keep JSON exact/raw where needed.

Acceptance:

```bash
caliper rates catalog
caliper rates catalog --model gpt-5.5 --limit 3
caliper rates catalog --format json
```

Expected: table output is scan-friendly; JSON remains machine-friendly.

### 8. Make TUI shortcut scope explicit or truly global

Problem: shortcut navigation reaches every screen when returning to Home between
jumps. In rapid use, pressing `b` or `i` while already on What-If did not jump
to Budgets or Insights.

Fix:

- Make app-level shortcuts global across secondary screens, or
- Update TUI help/README wording to say `Escape` returns Home before choosing
  another screen.

Acceptance:

In a Textual pilot:

```text
w -> WhatIfScreen
b -> BudgetsScreen
i -> InsightsScreen
```

Expected: shortcuts behave like the help text implies.

### 9. Preserve `NO_COLOR` during theme cycling

Problem: `NO_COLOR=1` initially selects monochrome, but pressing `t` can move
the app to a colored theme.

Fix:

- If `NO_COLOR` is set, keep active theme monochrome regardless of `t`, or cycle
  only no-color-safe variants.
- Optionally show a small notification that `NO_COLOR` is locking color themes.

Acceptance:

```bash
NO_COLOR=1 caliper tui --demo
```

In a Textual pilot, press `t`.

Expected: the active theme remains monochrome, or the override is explicit and
documented.

### 10. Show exact rate-limit percentages in the TUI Home panels

Problem: CLI statusline can show rate-limit percentages, but TUI Home panels can
show only bars/dashes without the exact percent values.

Fix:

- Add exact primary and weekly percentage text next to the bars.
- If reset/burn cannot be computed, explain why in compact language.

Acceptance:

Use a fixture with primary `75%` and weekly `80%` samples.

```bash
caliper statusline --compact
caliper tui
```

Expected: the TUI Home screen exposes the same limit percentages that the
statusline can report.

## Keep Green

Do not regress these verified 0.0.23 behaviors:

- `uvx --isolated --refresh --from caliper-ai==0.0.23 caliper --version` works.
- `pipx run --spec caliper-ai==0.0.23 caliper --version` works.
- Fresh venv local wheel install reports `0.0.23`.
- `uv run ruff check .` passes.
- `uv run ruff format --check .` passes.
- `uv run pytest` passes.
- `CALIPER_SMOKE_VERSION=0.0.23 scripts/live-release-smoke.sh` passes.
- `scripts/release-smoke.sh` passes.
- Wheel and sdist pass `twine check`.
- Empty first-run overview lists all checked vendors and next commands.
- Default human output redacts the session root.
- `--show-paths` restores full paths intentionally.
- Unknown model pricing shows `n/a` in model/session tables.
- `rates catalog` defaults to a capped table and offers filter flags.
- Markdown compare/what-if output uses `$`, commas, and `%`.
- TUI demo and real-data navigation reach every real screen.
- `NO_COLOR=1` initially selects the monochrome theme.

## Final Recommendation

Ship 0.0.23 as a serious beta if launch timing matters.

Before calling the UX perfect, fix the four P1 issues:

1. Default JSON repo/session identifier exposure.
2. Dollar-cell truncation in 80-column reports.
3. Mixed aggregate pricing labels.
4. Baseline-zero compare percentages.

Those are the findings most likely to become hostile public comments because
they hit the core promise: trusted local cost reporting.
