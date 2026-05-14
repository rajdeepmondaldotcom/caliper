# Implementation Plan: Release Plumbing Fix and Textual Maximum-Strength UX

## 1. Anchor

This document owns three things. The release workflow verify step. The
Textual interactive surface in `src/caliper/tui/`. The Claude attribution
scrub in non-commit text. It does not own pricing, parser behaviour, the
classic CLI render path, or the persona copy rules. Where this plan
touches the TUI, the persona rules in `docs/persona-overhaul/01-plan.md`
win on copy. This plan wins on widget choice, screen wiring, theme
tokens, command palette, snapshot tests, and release plumbing. Phase 1
is the plan. Implementation waits for `proceed`.

## 2. The three asks, restated

**A. Release CI is broken on the post-publish verify step.**
`uvx --refresh "caliper-ai==X" caliper --version` resolves the version
spec as the executable name. The fix is one flag. We also need a clean
local fallback that reads `.env` so the user can publish without
depending on CI, and a recovery for the dead `v0.0.7` tag.

**B. The Textual surface is a scaffold.** Twelve screens are stubs. No
bespoke themes are registered. No command palette. No real widgets
beyond a sparkline. Phase 1 lays out every screen, theme, widget, and
test needed to ship a workspace that feels engineered.

**C. Claude attribution is in past commit trailers, not in tracked
files.** A repo grep for "Co-Authored-By" and "built with Claude"
returns zero hits inside tracked source. Every `Claude` reference in
the tree is the vendor product name (`Claude Code`). Phase 1 sets
policy for new commits and adds a guard so the trailer cannot return.

## 3. Section A: Release CI fix and `.env`-driven manual publish

### 3.1 The exact bug

`.github/workflows/release.yml:181` runs:

```yaml
if uvx --refresh "caliper-ai==${{ steps.ver.outputs.version }}" caliper --version; then
```

`uvx` treats the first positional as the executable name.
`caliper-ai==0.0.6` is not an executable. The error in CI reads:
`An executable named 'caliper-ai' is not provided by package 'caliper-ai'`.
This has failed on 0.0.3, 0.0.4, 0.0.5, 0.0.6. PyPI uploads succeeded
each time. Only the verify step is wrong.

### 3.2 The patch

Replace the offending line. Diff:

```diff
-            if uvx --refresh "caliper-ai==${{ steps.ver.outputs.version }}" caliper --version; then
+            if uvx --refresh --from "caliper-ai==${{ steps.ver.outputs.version }}" caliper --version; then
```

One flag. Nothing else in `release.yml` changes.

### 3.3 Local publish runbook keyed off `.env`

Add `docs/release-and-ux-overhaul/RUNBOOK-publish.md` with the exact
steps. The `.env` file at the repo root already contains the token. It
is git-ignored. Do not modify the ignore rules.

Runbook contents:

1. Confirm `pyproject.toml` `version` matches the tag you intend to
   push.
2. `set -a; source .env; set +a` to load `TWINE_USERNAME`,
   `TWINE_PASSWORD` (and the alias `PYPI_API_TOKEN`).
3. `rm -rf dist && uv run python -m build`.
4. `uvx twine check dist/*`.
5. `uvx twine upload dist/*`.
6. Poll:
   `for i in 1 2 3 4 5 6; do uvx --refresh --from "caliper-ai==$VER" caliper --version && break; sleep 15; done`.
7. `git tag -a "v$VER" -m "v$VER"`, `git push origin "v$VER"`.

The runbook explicitly states `.env` never leaves the developer machine
and is not consumed by any CI step.

### 3.4 Recovery for the dead `v0.0.7` tag

The tag `v0.0.7` points at a commit whose `pyproject.toml` still reads
`version = "0.0.6"`. The release workflow's "Validate tag matches
pyproject version" step rejects this. Branch protection rejects amend
or force-push.

Plan:

1. Leave `v0.0.7` in place. It is harmless: PyPI never received a
   `0.0.7`. The tag does not block PyPI directly.
2. Open a normal commit on `main`: bump `pyproject.toml` to `0.0.8`,
   append a `## 0.0.8` block to `CHANGELOG.md` summarising the fixes
   from Section A plus any Section B/C work that lands in the same
   release window.
3. Push, then `git tag -a v0.0.8 -m "v0.0.8"`, then
   `git push origin v0.0.8`.
4. Add a short note to `CHANGELOG.md` under `0.0.8` documenting that
   `v0.0.7` was a stale tag and was skipped intentionally.

### 3.5 Regression test

Add `tests/test_release_workflow.py`. It reads
`.github/workflows/release.yml` as text and asserts:

1. Every `uvx --refresh` line that is followed by a `==` spec also
   contains `--from`.
2. The validate-tag step exists.
3. The pypi-publish step uses `${{ secrets.PYPI_API_TOKEN }}`.

This is plain string scanning, no YAML loader required, runs in
milliseconds, and lives in the existing 90%+ coverage pytest suite.

## 4. Section B: Textual maximum-strength UX

### 4.0 The UX standard

Every screen obeys five rules. No exceptions.

1. **One decision in the first three seconds.** A headline number, a
   delta, a vendor chip, an insight callout. Not a wall of rows.
2. **Progressive disclosure.** The top of the screen is a tight
   summary. The body is a `DataTable` you can sort and filter. The
   bottom is a footer with the next action. Drill-down happens on
   `enter`, not on first paint.
3. **Per-vendor split parity with the classic CLI.** Every grouped
   screen (Intervals, Sessions, Projects, Models) renders one tab or
   one segment per tool vendor when multiple vendors are present.
   Single-vendor windows render flat. Mirrors the v0.0.7 classic
   behaviour exactly.
4. **Insight beats datapoint.** Each screen reserves a slot at the top
   for a single `Notice` in voice. Insight engine fills it. When no
   insight applies the slot becomes a constraint chip naming the
   active window so the user can never lose context.
5. **No dumb scrolling.** Tables paginate or filter; never dump 500
   rows. Trees collapse non-focused branches. Live screen caps the
   visible event list at 50 rows.

### 4.1 Per-screen replacement plan

Twelve stubs live in `src/caliper/tui/screens/stub.py`. Each gets its
own file under `src/caliper/tui/screens/`, replaces `_StubScreen` with
a real `Screen`, and answers one question in the first three seconds.
The table is the contract.

| File (new) | Question answered in 3s | Primary widget | Secondary widget | Footer pills |
| --- | --- | --- | --- | --- |
| `sessions.py` | Which sessions cost the most this window. | `DataTable` (cost, tokens, model, vendor, started_at). Click-to-sort. Row-enter opens `SessionDrawer`. | `Sparkline` of per-session cost over the window. | `r refresh . e export . d doctor` |
| `intervals.py` | What did each day, week, month cost. | `TabbedContent` with three `Tab`s: Daily, Weekly, Monthly. Each tab hosts a `DataTable`. | Cohort sparkline strip at the top. | `r . [ prev . ] next . t theme` |
| `projects.py` | Which working directory is the biggest spender. | `Tree` over project paths (depth-aware roll-up). | `DataTable` for the focused node's child paths. | `r . enter drill . esc up` |
| `models.py` | Which model + tier combination is bleeding the budget. | Two-pane: tool-vendor `DataTable` left, model-vendor breakdown `DataTable` right. | `VendorChip` cluster at the top. | `o only-vendor . t theme . r` |
| `limits.py` | Where the 5h, weekly, and weekly-Opus limits stand. | Three `BurnGauge` widgets stacked. | `Notice` panel with ETA-to-100 text. | `r . d doctor . esc` |
| `live.py` | What is happening right now. | `watchdog`-driven file watcher. Pulse-underlined `Static` event log. | `BurnGauge` x2 + `Sparkline`. | `space pause . c clear . r` |
| `forecast.py` | What is the trend and the ±1σ band. | `Sparkline` + projection overlay. | `DataTable` of point estimates + bands. | `w ewma . l linear . r` |
| `whatif.py` | What changes if I swap tier or model. | Two `Input`s (model, tier) + a delta `DataTable`. | `DecisionPill` showing the spend delta. | `enter apply . r reset` |
| `budgets.py` | Which budgets are about to breach. | `DataTable` of budgets with `BudgetGauge` per row. | `Notice` list of `BudgetAlert`s. | `e edit . r refresh` |
| `insights.py` | What are the three highest-value heuristics now. | Card stack (three `Notice`s with `DecisionPill` per card). | None. | `enter act . esc home` |
| `doctor.py` | What is broken in the environment. | `DataTable` of probes + status. | `Notice` block per failing probe. | `r rerun . esc` |
| `receipt.py` | Show this window as a shareable receipt. | Markdown render of the receipt body. | Export button group. | `e export . y copy . esc` |

Drawers (one per screen that uses one) live under
`src/caliper/tui/drawers/`. They are `ModalScreen` subclasses so they
overlay cleanly and respect the keymap.

### 4.1.1 Per-vendor split inside Textual screens

The v0.0.7 classic CLI splits every grouped report by tool vendor.
The Textual workspace must mirror that. The contract:

- **Intervals.** Inside the screen there is a vendor `Tabs` row above
  the `TabbedContent` for Daily/Weekly/Monthly. One vendor tab per
  active vendor plus an `All` tab. Switching vendor reflows the three
  sub-tabs without re-running the parser.
- **Sessions.** A `Tabs` row at the top with one tab per vendor plus
  `All`. The DataTable below filters its rows in place.
- **Projects.** The root `Tree` carries vendor nodes as the first
  level. Each vendor expands into its working directories. `Tree`
  collapses every node except the focused vendor on first paint.
- **Models.** Already two-pane (tool vendor left, model vendor right).
  No change beyond ensuring the left pane preserves per-vendor cost
  ordering.
- **Forecast, WhatIf, Budgets, Insights, Doctor, Receipt, Limits,
  Live.** Not naturally per-vendor. They render flat but expose a
  `--only` and `--only-vendor` filter via the existing CLI flags and
  the command palette.

A new regression test `tests/test_grouped_per_vendor_parity.py`
asserts the classic CLI behaviour still holds: feed a multi-vendor
result through each grouped command, count tables in the stdout, and
assert it matches the vendor count. This protects v0.0.7 from
silent regression while Section B lands.

### 4.2 Themes

Four bespoke themes registered in `CaliperApp.on_mount` via
`self.register_theme(...)` against a small `Theme` factory. TCSS
palette tokens live in:

- `src/caliper/tui/tcss/themes/slate.tcss` (dark, the default).
- `src/caliper/tui/tcss/themes/parchment.tcss` (light).
- `src/caliper/tui/tcss/themes/colorblind.tcss` (Okabe-Ito palette,
  no green/red contrast collisions).
- `src/caliper/tui/tcss/themes/monochrome.tcss` (no color, used under
  `NO_COLOR`).

`CSS_PATH` extends to a list of all four. `t` cycles. `_THEME_ORDER`
already exists. Persist the chosen theme to `caliper.toml` under
`[tui] theme =`. `NO_COLOR` forces `monochrome` and disables the
cycle key. Each theme is verified for WCAG AA contrast in a unit test
that reads the token table and computes pairs.

### 4.3 Command palette provider

Add `src/caliper/tui/palette.py` with a `CaliperCommands(Provider)`
subclass. Wire it in `CaliperApp.COMMANDS = {*App.COMMANDS,
CaliperCommands}`. The provider yields:

- `Go to <screen>` (one entry per screen in `_SCREENS`).
- `Refresh`.
- `Cycle theme`.
- `Toggle redact`.
- `Open caliper.toml`.
- `Export receipt`.
- `Run doctor`.
- `Refresh rates`.

Each entry returns a `DiscoveryHit` with a help string written in
voice. The palette is bound to `ctrl+p`.

### 4.4 New widget inventory

| Widget (new file) | Consumers | Notes |
| --- | --- | --- |
| `widgets/decision_pill.py` | Home, WhatIf, Insights | Fixed-width inline `Static` with a colored prefix. |
| `widgets/constraint_chip.py` | Header strip across every screen | Compact label + value. |
| `widgets/burn_gauge.py` | Limits, Live | `ProgressBar` styled + ETA text. |
| `widgets/budget_gauge.py` | Budgets | `BurnGauge` variant with currency formatting. |
| `widgets/vendor_chip.py` | Models, Sessions row drawer, Cost card | Glyph + lower-case label. Mirrors persona plan section 4. |
| `widgets/pricing_drawer.py` | Sessions, Models, Receipt | `ModalScreen` showing the long-context multiplier and tier source. |
| `widgets/notice.py` | Insights, Doctor, Live, Budgets | `Static` with severity classes. |
| `widgets/sparkline.py` | exists | Reused, no change. |
| `widgets/cost_card.py` | exists | Vendor chip row added per the persona plan. |
| `widgets/loading_overlay.py` | exists | Reused. |

Each widget gets its own TCSS class. No inline styles outside the
widget file.

### 4.5 Snapshot test surface

Use `pytest-textual-snapshot` (already a dev dep). One snapshot test
per screen, three sizes each: 80x24, 120x40, 200x60. That is 12
screens times 3 sizes = 36 snapshots. Add an additional snapshot for
the command palette open state, the welcome wizard first run, and
each of the four themes on the Home screen. Total target: 44
snapshots. Files: `tests/snapshots/test_tui_screens.py` +
`tests/snapshots/test_tui_themes.py` +
`tests/snapshots/test_tui_palette.py`.

### 4.6 Welcome wizard

Replace `WelcomeScreen` in `stub.py` with
`src/caliper/tui/screens/welcome.py`. Shows once per machine. State
lives at `${XDG_CONFIG_HOME:-~/.config}/caliper/state.json` with a
single key: `{"welcome_seen_at": "<iso>"}`. Three steps: pick theme,
pick redact mode, confirm Codex log root.

### 4.7 Live screen with `watchdog`

`watchdog` is already in `pyproject.toml` deps. Use a
`PollingObserver` to keep cross-platform behaviour predictable in
tests, then upgrade to `Observer` on darwin and linux at runtime.
Debounce file events to 250 ms. On event arrival, set a `reactive`
flag that triggers a 500 ms underline pulse on the event log via
TCSS swap.

### 4.8 Footer and mouse parity

`Footer` shows a scope chip (window label), the last refresh time,
and decision pills. Every footer affordance is click-enabled by
binding the key on a `Static` widget with `on_click`. Every
`DataTable` row is double-click and Enter actionable. `TabbedContent`
tabs are clickable by default. Verified with a Textual
`App.run_test()` pilot test per screen.

### 4.9 Performance budget

`caliper tui --demo` must reach first paint within 200 ms on a
2024-era MacBook. Measured by a `pytest` benchmark using
`App.run_test()` and `pilot.pause()` timing. Real-load first paint
goes through `LoadingOverlay` so the perceived budget is met
regardless of parse time.

### 4.10 Accessibility

WCAG AA contrast asserted in `tests/test_tui_themes.py` by reading
TCSS color tokens and computing luminance ratios. Keyboard-only walk
across all 12 screens covered by a single pilot test in
`tests/test_tui_keyboard_walk.py`. Reduced-motion handled by skipping
the underline pulse when `NO_COLOR` is set.

## 5. Section C: Attribution scrub

### 5.1 Policy

Add the policy block to `CLAUDE.md` under a new top-level section
`## Commit attribution policy`. Text:

> New commits do not include `Co-Authored-By: Claude` trailers or
> "built with Claude" attribution lines. Past commits are left as-is.
> Branch protection blocks history rewrites. The vendor product name
> "Claude Code" and the model identifier "claude-opus-4.7" are not
> attribution. Leave them alone in copy, tests, and parsers.

### 5.2 Line-by-line replacement table

Grep across the tree finds zero attribution strings to replace. Every
`Claude` occurrence is the vendor product name. No edits to non-commit
text are required.

| File | Line | Current | Action |
| --- | --- | --- | --- |
| `README.md` | various | "Claude Code" vendor name | Keep |
| `CHANGELOG.md` | various | "Claude Code" vendor name | Keep |
| `docs/persona-overhaul/01-plan.md` | 43, 48 | "Claude Code" product | Keep |
| `docs/messaging/PITCH.md` | various | "Claude Code" product | Keep |
| `src/caliper/vendors/claude_code.py` | parser file | Keep |
| `tests/test_vendor_claude_code.py` | tests | Keep |
| `pyproject.toml` `keywords` | `"claude-code"` keyword | Keep |
| `src/caliper/pricing.py` | `"claude-opus-4.7"` model id | Keep |

### 5.3 Files explicitly excluded

`src/caliper/vendors/claude_code.py`, `tests/test_vendor_claude_code.py`
(if any), `pyproject.toml` keyword list, `src/caliper/pricing.py`
model ids, every doc that names `Claude Code` as a tool vendor.
Excluded permanently.

### 5.4 Guard

Add `tests/test_attribution_policy.py` that walks the tree and fails
if a tracked file (not under `tests/fixtures/` or `vendors/`) contains
the literal string `Co-Authored-By: Claude` or `built with Claude` or
`written by Claude` or `generated by Claude`. The vendor product name
`Claude Code` is whitelisted. Runs in the standard `pytest`
invocation.

## 6. Edge cases and risks

1. PyPI propagation can lag five minutes. The verify step already
   retries six times with 15 s sleeps. Keep that budget.
2. `uvx --refresh --from` still hits the cache layer. The `--refresh`
   flag is the cache buster, not `--from`. Confirmed in `uv` docs.
   Keep both.
3. Textual `register_theme` API requires Textual 0.86+. Project pins
   `textual>=8.2,<9`. The `Theme` factory in 8.2 supports register at
   app init. Confirm before commit B-02.
4. `watchdog` `Observer` on Linux uses inotify and can hit per-user
   watch limits on big trees. Default to `PollingObserver` in CI,
   runtime detect elsewhere.
5. Snapshot tests under three sizes per screen will balloon the
   snapshot directory by ~44 SVG files. Acceptable. Pin width and
   color_system as per CLAUDE.md.
6. Branch protection blocks force-push. Recovery for the stale
   `v0.0.7` tag goes via `0.0.8`, not via amend.

### 4.11 Structured hierarchy, not information dump

Every screen has the same three-band layout enforced via TCSS:

- **Top band (3 lines max).** Section header + scope chip + one
  `Notice` from the insight engine. Sets the question.
- **Middle band (1fr).** The primary widget. Scrolls if needed.
  Never dumps more than 50 rows at first paint; the rest is one
  keystroke away.
- **Bottom band (1 line).** Footer with the decision pills for that
  screen, last refresh time, and the four globally-bound actions
  (`r refresh`, `?`, `q quit`, `t theme`).

The layout is enforced by a `Screen` base class `CaliperScreen` in
`src/caliper/tui/screens/_base.py` that wires the three bands as
named `Container`s. Every real screen subclasses it. The contract
test `tests/test_tui_screen_layout.py` reads each screen's compose
tree and asserts the three-band invariant.

## 7. Acceptance criteria

- [ ] `release.yml` post-release smoke step contains `--from` on every
      spec-based `uvx --refresh` line.
- [ ] `tests/test_release_workflow.py` passes locally and in CI.
- [ ] `docs/release-and-ux-overhaul/RUNBOOK-publish.md` exists and
      references `.env` only by name.
- [ ] `0.0.8` ships from CI with the verify step green.
- [ ] `src/caliper/tui/screens/` contains one real screen per stub.
      `stub.py` only holds compatibility shims if needed.
- [ ] Four themes register at launch. `t` cycles. `NO_COLOR` pins
      monochrome.
- [ ] Command palette opens on `ctrl+p` and lists every action in the
      table above.
- [ ] Every screen has at least one snapshot at 80x24, 120x40, 200x60.
- [ ] `caliper tui --demo` reaches first paint in ≤200 ms.
- [ ] All four themes pass WCAG AA contrast for text on background
      tokens.
- [ ] Keyboard-only walk test reaches every screen and returns Home.
- [ ] `tests/test_attribution_policy.py` passes.
- [ ] `CLAUDE.md` carries the attribution policy block.
- [ ] `tests/test_grouped_per_vendor_parity.py` asserts the v0.0.7
      classic-CLI per-vendor split still holds across daily, weekly,
      monthly, session, project, models, blocks.
- [ ] Every Textual screen wires its compose tree through the
      `CaliperScreen` three-band base (top / middle / footer).
- [ ] Intervals, Sessions, Projects, Models inside the Textual
      workspace each carry a vendor `Tabs` row that mirrors the
      classic CLI per-vendor split.
- [ ] No screen renders more than 50 rows at first paint. Tables
      paginate, trees collapse, live event list caps.

## 8. Commit phasing

Atomic, numbered, mergeable independently where possible.

1. **A-01**: `fix(ci): pass --from to uvx in post-release smoke`. One-line
   change. Adds `tests/test_release_workflow.py`.
2. **A-02**: `docs(release): add .env publish runbook`. Adds
   `docs/release-and-ux-overhaul/RUNBOOK-publish.md`.
3. **A-03**: `chore: bump version to 0.0.8 and skip stale v0.0.7 tag`.
   Adjusts `pyproject.toml` and `CHANGELOG.md`.
4. **B-01**: `feat(tui): register four bespoke themes`. New TCSS files
   + theme registration.
5. **B-02**: `feat(tui): command palette provider`. New `palette.py`
   + binding.
6. **B-03**: `feat(tui): real Sessions screen with DataTable`. Replaces
   stub.
7. **B-04**: `feat(tui): real Intervals screen with TabbedContent`.
   Replaces stub.
8. **B-05**: `feat(tui): real Projects screen with Tree`. Replaces
   stub.
9. **B-06**: `feat(tui): real Models screen with two-pane vendor
   split`. Replaces stub.
10. **B-07**: `feat(tui): real Limits screen with BurnGauge`. Replaces
    stub.
11. **B-08**: `feat(tui): real Live screen with watchdog`. Replaces
    stub.
12. **B-09**: `feat(tui): real Forecast + WhatIf screens`. Replaces
    both.
13. **B-10**: `feat(tui): real Budgets + Insights screens`. Replaces
    both.
14. **B-11**: `feat(tui): real Doctor + Receipt screens`. Replaces
    both.
15. **B-12**: `feat(tui): welcome wizard with state.json`. Replaces
    `WelcomeScreen`.
16. **B-13**: `test(tui): snapshot, keyboard walk, contrast, perf`.
    Snapshots + assertions.
17. **C-01**: `docs: attribution policy in CLAUDE.md`. Single block.
18. **C-02**: `test: guard against Claude attribution trailer drift`.
    Adds `tests/test_attribution_policy.py`.
19. **B-14**: `feat(tui): CaliperScreen three-band base + screen
    layout test`. Establishes the structural contract before any
    real screen lands so the rest of Section B can subclass it.
20. **B-15**: `feat(tui): vendor Tabs row on Intervals, Sessions,
    Projects, Models`. Mirrors the v0.0.7 classic per-vendor split
    inside the workspace.
21. **A-04**: `test(cli): pin per-vendor parity on grouped reports`.
    `tests/test_grouped_per_vendor_parity.py`. Independent of
    Section B so it can ship in the same 0.0.8 release as A-01..A-03.

## 9. Open questions for the user

1. **PyPI verify retry budget.** Keep at 6×15 s, or extend? Default:
   keep.
2. **Theme default.** Slate dark, or follow OS appearance? Default:
   slate, override via `caliper.toml`.
3. **Welcome wizard storage path.** `${XDG_CONFIG_HOME}/caliper/state.json`,
   or under the existing `caliper.toml`? Default: the JSON sidecar
   (avoids touching the TOML schema this release).
4. **Watchdog mode.** PollingObserver everywhere, or native per OS?
   Default: native at runtime, polling in CI.
5. **Snapshot inflation.** 44 SVGs land in `tests/__snapshots__/`.
   Accept? Default: yes.
6. **Bump path.** Skip `0.0.7` entirely and ship `0.0.8`, or retag
   `0.0.7` to a new commit? Default: skip and ship `0.0.8`.

## 10. Non-goals

- Rewriting commit history.
- Touching the classic CLI render path.
- Adding network calls for theme assets or font downloads.
- Building a web UI.
- Changing `pyproject.toml` deps beyond what existing widgets need.
- Editing `Claude Code` vendor references.

## 11. Definition of done

- 0.0.8 ships from CI with the verify step green.
- A user can run the `.env` runbook end-to-end and reach a verified
  install.
- `caliper tui --demo` boots into a real workspace with twelve real
  screens, four themes, a command palette, mouse parity, and a
  welcome wizard on first run.
- Snapshot, contrast, keyboard, and performance tests all pass.
- New commits do not carry Claude attribution. The guard test
  enforces it.

WAITING FOR CONFIRMATION. The implementation has not started. Reply
`proceed` to begin, `modify: ...` to change scope, or ask any of the
open questions.
