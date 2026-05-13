# Phase 8 — Post-Implementation Audit

**Status:** Draft (Phase 8)
**Date:** 2026-05-14
**Method:** walked every line of the Phase 6 final plan against the
delivered commits (`57a6014` → `ce51a5a`) and the working tree. The
findings below are deliberately honest: what is finished, what is
partially shipped, what is deferred. Phase 9 closes the gaps that fit
in this round; the rest is tracked as follow-up.

---

## 1. Snapshot of what landed

Sixteen commits on top of the previous HEAD (`602a212`):

```
57a6014  chore(deps): bump rich floor to 14.2.0 (textual prereq)       P0
050ebe6  feat(parser): optional ParseProgress hook on load_usage        P1
2957c66  feat(insights): build_insights_from accepts pre-built          P2
66d481a  feat(vendors): public vendor_file_count(options) helper        P3
229fde9  feat(parse_cache): ParseCache.clear() drops all rows           P4
cf592cf  feat(budgets): serialize_budgets() inverse of parse_budgets    P5
bb70792  feat(config): TuiConfig dataclass + [tui] section reader       P6
82388c4  refactor(humanize): public sparkline() promoted from live._   P7
b532b4f  refactor(exporters): session_compat_json promoted from cli     P8
d0593f8  feat(scenarios): days_for_interval(interval) helper            P9
e7a3a7e  chore(build): ship src/caliper/tui/tcss/*.tcss in wheel + CI  P10
896b393  chore(tui): add textual + watchdog to optional [tui] extra    T01
319ab63  feat(tui): scaffold caliper.tui package + run_tui + cli       T02+T03
ce51a5a  feat(tui): state mediator, workers, widgets, Home + stubs    T04-T08
```

Plus 6 planning docs (Phases 1–6) and 1 perf refactor that pre-dated
the TUI work (`overview` aggregation hoist).

## 2. What is fully delivered

### Prerequisites (P0–P10) — **100% complete**

Every prerequisite commit ships its own test coverage and keeps CLI
output byte-identical. The full test suite is **388 tests green**
under `uv run pytest`. CI wheel-content check is wired in
`.github/workflows/ci.yml`.

### Foundations (T01–T03)

- Optional `[tui]` extra pins `textual>=8.2,<9` and
  `watchdog>=4.0,<7`.
- `caliper tui` command accepts `--demo`, `--vendors`, `--since`,
  `--until`, `--days`, `--no-watchdog`. Friendly install hint when the
  extra is absent. Refuses non-TTY stdout unless `--demo`.

### Engine (T04–T08, partial — see §3.2 below for what is real)

- `caliper.tui.state.AppSnapshot` + `Scope` + `apply_scope` mediator.
- `caliper.tui.workers` reuses the existing `parser.load_usage`,
  `aggregate_*`, `build_insights_from`, `compute_window_state`, and
  `load_rate_card` without re-deriving anything.
- `caliper.tui.progress.TextualParseProgress` bridges the new
  `ParseProgress` callback to the Textual message bus with
  `Worker.is_cancelled` polling.
- `caliper.tui.messages` defines `LoadStarted`, `LoadFileDone`,
  `LoadFileCacheHit`, `LoadFinished`, `LoadSucceeded`, `LoadFailed`,
  `LoadCancelled`, and the `WorkerCancelled` exception.
- `caliper.tui.demo.materialize_demo` writes deterministic JSONL into a
  tempdir so `--demo` exercises the real parser path.
- Widgets: `Sparkline`, `CostCard`, `WindowPanel`, `LoadingOverlay`.
- `HomeScreen` renders three cost-window cards, the two limit panels,
  insights feed, and recent sessions. Reactive: `watch_snapshot`
  forwards every new snapshot to the screen.
- Twelve stub screens keep the `1..9` keymap navigable end-to-end.
- App keymap: `q`, `?` (notification toast), `r`, `t`, `1..9`.

A manual smoke (`caliper tui --demo` against the synthetic fixture)
boots without crashes, prints the header / footer / insights / recent
panels, and exits cleanly on `q`. The CLI test suite is unchanged.

## 3. Deviations from the final plan

### 3.1 Commits bundled — intentional

The plan budgeted T04, T05, T06, T07, T08 as five separate commits.
They landed as **one commit (`ce51a5a`)**.

Rationale: the bundles are tightly coupled — `HomeScreen` cannot mount
without `AppSnapshot`; `AppSnapshot` cannot populate without the
worker; the worker cannot post progress without `TextualParseProgress`
and the message classes. Splitting into five micro-commits would have
produced four intermediate commits that don't boot.

Phase 8 records this as a deliberate deviation, not a defect. Phase 9
will produce a `feat(tui): T04..T08 bundle note` entry in CHANGELOG so
the deviation is traceable.

### 3.2 Stub screens — partial

Of the 16 screens promised in §5 of the final plan:

| Screen | Status |
| --- | --- |
| `home.py` | **complete** with reactive snapshot wiring |
| `sessions.py` | **stub** (navigates, shows placeholder) |
| `intervals.py` | stub |
| `projects.py` | stub |
| `models.py` | stub |
| `limits.py` | stub |
| `live.py` | stub |
| `forecast.py` | stub |
| `whatif.py` | stub |
| `budgets.py` | stub |
| `insights.py` | stub |
| `doctor.py` | stub |
| `receipt.py` | stub |
| `welcome.py` | stub |
| `help.py` | **absent** — Help is a toast notification from `?` for now |
| Command palette | **absent** — `Ctrl+P` falls back to Textual default |

This is the largest gap. The TUI is **navigable and demo-able** but
the *workspace* depth promised in Phase 1 §0 is only realised on the
Home screen today.

### 3.3 Themes — partial

`TuiConfig.theme` is read and persisted. The app *attempts* to set
`self.theme` to one of (`slate`, `parchment`, `colorblind`,
`monochrome`) when those themes are registered, falling back to
Textual built-ins (`textual-dark`, `textual-light`, `nord`,
`textual-ansi`). The four bespoke themes themselves are **not
registered** — the TCSS palette stays Textual's default.

`action_cycle_theme` advances `TuiConfig.theme` and shows a toast, but
visually the user only sees Textual's built-ins flip.

### 3.4 Watchdog filesystem watcher — absent

The dependency is pinned in `[tui]` but no `caliper.tui.watch` module
ships yet. The Live screen is a stub; no debounced refresh path
exists. `--no-watchdog` is accepted but currently has no real effect
because there is nothing to disable.

### 3.5 Pilot snapshot tests — not landed

`pytest-textual-snapshot` was not yet added to the dev dep group, and
there are no snapshot tests under `tests/tui/snapshots/`. Today
`tests/tui/test_tui_imports.py` exercises only:

- That `caliper.tui` imports.
- That `state`, `messages`, `widgets`, `screens` import.
- That `apply_scope` returns a new snapshot and clears the cache.

### 3.6 README / docs-site / CHANGELOG — not landed

T26 (README section + screencast) and T27 (CHANGELOG entry) are
pending.

### 3.7 First-paint budget — not measured

The plan committed to ≤200 ms for `--demo`. No timing instrumentation
has been added; the manual smoke test felt subjectively snappy but
nothing in CI verifies the budget.

## 4. Items that were planned and are absent (recap)

| ID | Planned | Status |
| --- | --- | --- |
| T07 widgets | `scope_chips`, `pricing_transparency`, `budget_gauge`, `onboarding_step`, `time_scrubber`, `notice` | **only sparkline / cost_card / window_panel / loading_overlay shipped** |
| T09–T20 screens | full real implementations | **stubs only** |
| T21 command palette | `CaliperCommands` Provider | absent (Textual default palette only) |
| T22 welcome wizard | first-run celebration | absent |
| T23 scope chips + scrubber | interval `[`/`]` step | absent (no key bound) |
| T24 themes + NO_COLOR | four registered themes | partial (logic present, TCSS theme files absent) |
| T25 snapshot suite | per-screen × 3 resolutions | absent |
| T26 docs | README + screencast | absent |
| T27 CHANGELOG | release notes | absent |
| Watchdog + debounce | live FS events | absent |
| pytest-textual-snapshot | dev dep | absent |
| Privacy invariant test | rendered-tree grep | absent |

## 5. Items that came in over-spec — none

No accidental scope creep. Every commit traces back to a plan line.

## 6. Risks observed during implementation

- The `[tui]` install pulls a lot of transitive deps (markdown-it-py,
  uc-micro-py, etc.). The base `caliper-ai` install is still small;
  only opt-in users pay the cost. **OK.**
- The hatchling `force-include` recipe in the plan duplicated files in
  the wheel; switching to `artifacts = ["src/caliper/tui/tcss/*.tcss"]`
  fixed it. The plan-document recipe should be amended in Phase 9.
- The `_compat_session_id_json` shim now indirects through
  `caliper.exporters.session_compat_json`, which adds a couple of
  imports. Existing tests pass — but the schema-export contract should
  still be exercised end-to-end before T20 lands.

## 7. Phase 9 — must-fix list

Phase 9 will address these *small, well-scoped* fixes; the larger
scope (T09–T27) is tracked as roadmap, not Phase 9 work.

1. **Plan correction:** amend the Phase 6 hatchling recipe to use
   `artifacts` (delivered) instead of `force-include` (which
   duplicated files in dev).
2. **CHANGELOG entry:** a brief, honest note about the new `[tui]`
   extra and the `caliper tui` command. Mark the rest of the
   workspace as in-progress.
3. **README section:** one paragraph + the install line +
   `caliper tui --demo` invitation.
4. **`pytest-textual-snapshot`:** add to dev deps so the snapshot
   workflow is ready when screens land.
5. **One pilot snapshot:** add a single `HomeScreen` snapshot test so
   T09–T20 have a working example to model after.
6. **Worker-cancel unit test:** confirm `TextualParseProgress`
   raises `WorkerCancelled` when its worker is cancelled.
7. **Time-scrubber binding:** wire `[` / `]` to no-op + toast so the
   keymap promise is preserved until T23 lands the real action.

## 8. Verdict

Caliper now ships a **navigable, demo-able Textual TUI** built on top
of eleven small, atomic prerequisite improvements that strictly
improve the rest of the codebase. The Home screen reflects the design
intent. Every other screen is a stub.

Continuing through T09–T27 is straightforward — the wiring is in
place, the data flows, and the empty screens have a known shape.

Phase 9 makes the partial state safe and discoverable, then closes
Phase 7 with a clean handoff.
