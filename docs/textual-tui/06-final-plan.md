# Phase 6 — Final Consolidated Implementation Plan: Textual TUI

**Status:** Final (Phase 6) — source of truth for Phase 7 implementation.
**Date:** 2026-05-14
**Supersedes for implementation:** `01-initial-implementation-plan.md`,
`03-plan-revision-r1.md`, `05-plan-revision-r2.md`.
**Retains for history:** `02-self-audit.md`, `04-industry-research.md`.

If anything in earlier docs disagrees with this one, **this one wins**
for implementation. The audits and research stay for posterity so
reviewers can replay the reasoning.

---

## 1. Mission (one paragraph)

Ship a single-process, pure-Python, offline-first Textual TUI for
Caliper. One keystroke from `pip install 'caliper-ai[tui]'` puts the
user inside a calm, opinionated workspace that answers "what did this
PR cost", "am I about to blow my plan", "which model and tier is
bleeding me", and "what changes if I swap tier or model" — without
re-deriving any cost math, without phoning home, and without breaking
the existing Typer CLI.

## 2. Architecture (locked)

- **One Python process.** Textual screens import `caliper.*` directly.
- **Reactive mediator.** A single `AppSnapshot` flows from `AppState`
  to all screens. Mutations go through `apply_scope(...)`.
- **Workers, not threads.** `@work(thread=True, exclusive=True,
  group="data", exit_on_error=False)` for IO; coroutines for everything
  else.
- **Pure Python.** No Node, no IPC, no JSON wire.
- **Frozen value objects.** All cost math + window state types stay
  frozen. Only `AppState` and screen widgets hold mutable state.
- **Optional `[tui]` extra.** Base install stays Rich-only.

## 3. Module layout

```
src/caliper/tui/
  __init__.py        # public: run_tui(options), CaliperApp
  app.py             # CaliperApp(App) + bindings + provider registration
  state.py           # AppSnapshot + apply_scope mediator + RefreshReason
  workers.py         # load_usage_worker, rate_card_worker, aggregate_worker,
                     # whatif_worker, health_worker, watch_worker
  messages.py        # LoadStarted, LoadFileDone, LoadFinished, LoadCancelled,
                     # LoadSucceeded, LoadFailed, ScopeChanged, ThemeChanged
  watch.py           # choose_observer(paths), debounce, --no-watchdog support
  progress.py        # TextualParseProgress + WorkerCancelled
  clipboard.py       # OSC52 emitter, pyperclip fallback, inline-receipt fallback
  commands.py        # CaliperCommands(Provider) for command palette
  theme.py           # SLATE, PARCHMENT, COLORBLIND, MONOCHROME Theme objects
  config.py          # TuiConfig accessor over caliper.config
  demo.py            # caliper tui --demo data fixture (in-memory)
  screens/
    welcome.py home.py intervals.py sessions.py projects.py models.py
    limits.py live.py forecast.py whatif.py budgets.py insights.py
    doctor.py receipt.py help.py
  widgets/
    cost_card.py sparkline.py window_panel.py budget_gauge.py
    scope_chips.py pricing_transparency.py loading_overlay.py
    notice.py onboarding_step.py time_scrubber.py
  tcss/
    base.tcss slate.tcss parchment.tcss colorblind.tcss monochrome.tcss
```

Tests:

```
tests/tui/
  __init__.py
  conftest.py
  test_tui_app_boot.py
  test_tui_workers.py
  test_tui_scope_step.py
  test_tui_themes.py
  test_tui_keymap.py
  test_tui_privacy.py
  test_tui_demo_mode.py
  test_tui_doctor_actions.py
  test_tui_clipboard.py
  test_tui_watch.py
  snapshots/
    __snapshots__/
    README.md
    test_home.py
    test_intervals.py
    test_sessions.py
    test_projects.py
    test_models.py
    test_limits.py
    test_live.py
    test_forecast.py
    test_whatif.py
    test_budgets.py
    test_insights.py
    test_doctor.py
    test_receipt.py
    test_welcome.py
    test_help.py
    test_command_palette.py
```

## 4. Dependency surface

```toml
[project]
dependencies = [
  "platformdirs>=4.3",
  "rich>=14.2.0",
  "typer>=0.12",
]

[project.optional-dependencies]
prom = ["prometheus-client>=0.20"]
tui  = [
  "textual>=8.2,<9",
  "watchdog>=4.0,<7",
]

[tool.hatch.build.targets.wheel]
packages = ["src/caliper"]
artifacts = ["src/caliper/tui/tcss/*.tcss"]
```

*Phase 9 correction.* An earlier draft of this section used
`[tool.hatch.build.targets.wheel.force-include]`, which under
hatchling 1.26 emitted the `.tcss` files twice because the package
auto-include already picked them up. `artifacts` is the right knob
for non-Python files inside a discovered package directory.

`pyperclip` is **not** in the `tui` extra. OSC52 is the primary
clipboard path; pyperclip is only used when the user already has it
installed (we import-guard).

`pytest-textual-snapshot` lives in `[dependency-groups.dev]` only.

## 5. Eleven prerequisite commits (P0–P10)

These land **before** any Textual code. Each is a small, atomic,
green-on-CI change that the CLI already justifies.

| # | Commit | What it adds |
| --- | --- | --- |
| **P0** | `chore(deps): bump rich floor to 14.2.0 (textual prereq)` | Lift `rich>=14.2.0`. Snapshot existing renderers; fix any drift while keeping CLI output byte-identical. |
| **P1** | `feat(parser): optional ParseProgress hook on load_usage` | Add `progress: ParseProgress \| None = None` to `load_usage` + each vendor adapter. `ParseProgress` Protocol with `starting/file_done/cache_hit/finished`. |
| **P2** | `feat(insights): build_insights_from(*, total, projects, daily, rate_card, result)` | Avoid re-aggregating in TUI. Wrapper `build_insights` calls through. |
| **P3** | `feat(health): public vendor_file_count(options)` | Promote `_discovered_vendor_file_count` from `cli.py` to `health.py` (or `vendors/__init__.py`). |
| **P4** | `feat(parse_cache): ParseCache.clear() + vacuum` | Drops rows, vacuums, returns count removed. |
| **P5** | `feat(budgets): serialize_budgets(budgets) inverse of parse_budgets_table` | Round-trip property test. |
| **P6** | `feat(config): [tui] section + TuiConfig dataclass` | `theme`, `redact`, `show_demo_on_first_run`, `no_watchdog`. |
| **P7** | `refactor(humanize): public sparkline(values)` | Move from `live._sparkline`; `live.py` re-exports. |
| **P8** | `refactor(exporters): session_compat_json (was cli._compat_session_id_json)` | TUI receipt reuses CLI output. |
| **P9** | `feat(scenarios): days_for_interval(interval) helper` | What-If/Interval bridge. |
| **P10** | `chore(build): include src/caliper/tui/tcss/*.tcss in wheel + CI check` | hatchling `force-include` + grep step. |

All eleven keep CLI behavior byte-identical (verified by the existing
test suite remaining green).

## 6. Twenty-seven Textual commits (T01–T27)

| # | Commit |
| --- | --- |
| T01 | `chore(tui): add textual + watchdog to optional [tui] extra` |
| T02 | `feat(tui): scaffold caliper.tui package + run_tui entry` |
| T03 | `feat(cli): add caliper tui command (--demo, --vendors, --since, --until, --no-watchdog)` |
| T04 | `feat(tui): app shell + four themes (slate/parchment/colorblind/monochrome) + NO_COLOR auto-switch` |
| T05 | `feat(tui): AppSnapshot + reactive store + apply_scope mediator` |
| T06 | `feat(tui): workers + WorkerCancelled + TextualParseProgress + LoadingOverlay` |
| T07 | `feat(tui): widgets/sparkline + widgets/cost_card + widgets/window_panel + widgets/notice` |
| T08 | `feat(tui): screens/home (3-window overview + limits + insights + recent sessions)` |
| T09 | `feat(tui): screens/intervals (daily/weekly/monthly tabs + sortable DataTable)` |
| T10 | `feat(tui): screens/sessions (filter + detail drawer via session_compat_json)` |
| T11 | `feat(tui): screens/projects (Tree + side panel)` |
| T12 | `feat(tui): screens/models + PricingTransparency drawer` |
| T13 | `feat(tui): screens/limits (Textual reflow of WindowPanel)` |
| T14 | `feat(tui): screens/live (debounced watchdog/poll picker)` |
| T15 | `feat(tui): screens/forecast (linear + EWMA + save-as-budget)` |
| T16 | `feat(tui): screens/whatif modal (uses days_for_interval)` |
| T17 | `feat(tui): screens/budgets gauges + caliper.toml round-trip` |
| T18 | `feat(tui): screens/insights cards (uses build_insights_from)` |
| T19 | `feat(tui): screens/doctor + fix actions (rebuild parse cache, refresh rates)` |
| T20 | `feat(tui): screens/receipt clipboard (OSC52 / pyperclip / inline + tmux note)` |
| T21 | `feat(tui): command palette provider + 1..9 jumps + suspend-to-editor` |
| T22 | `feat(tui): welcome wizard + first-run flag in [tui]` |
| T23 | `feat(tui): scope chips + interval scrubber + redact toggle modal` |
| T24 | `feat(tui): NO_COLOR session override + ansi_color handling + a11y polish` |
| T25 | `test(tui): pilot snapshots 80x24/120x40/200x60 + privacy + keymap + clipboard` |
| T26 | `docs(tui): README section + screencast SVG + keymap reference + a11y note` |
| T27 | `chore(tui): release notes + CHANGELOG entry` |

## 7. Canonical types

```python
# src/caliper/tui/state.py
from dataclasses import dataclass, replace
from datetime import datetime
from caliper.intervals import Interval
from caliper.models import LoadResult, RuntimeOptions, Aggregate
from caliper.pricing import RateCard
from caliper.windows import WindowState
from caliper.insights import Insight
from caliper.budgets import BudgetAlert
from caliper.health import HealthCheck

@dataclass(frozen=True)
class Scope:
    interval: Interval
    show_dollars: bool = True
    show_credits: bool = True

@dataclass(frozen=True)
class AppSnapshot:
    options: RuntimeOptions
    scope: Scope
    load_result: LoadResult | None = None
    rate_card: RateCard | None = None
    overview_windows: tuple[Aggregate, ...] = ()
    overview_total: Aggregate | None = None
    daily: tuple[Aggregate, ...] = ()
    weekly: tuple[Aggregate, ...] = ()
    monthly: tuple[Aggregate, ...] = ()
    sessions: tuple[Aggregate, ...] = ()
    projects: tuple[Aggregate, ...] = ()
    models: tuple[Aggregate, ...] = ()
    insights: tuple[Insight, ...] = ()
    budget_alerts: tuple[BudgetAlert, ...] = ()
    primary_window: WindowState | None = None
    secondary_window: WindowState | None = None
    health: tuple[HealthCheck, ...] | None = None
    refresh_started_at: datetime | None = None
    refresh_completed_at: datetime | None = None
    refresh_error: str | None = None
```

Mutation always returns a new snapshot via `dataclasses.replace`.

## 8. UX pillars (16, re-anchored)

Each screen must satisfy these. They are the review checklist for
Phase 7 commits.

1. One question per screen.
2. Sentences, not labels.
3. Always-visible footer (scope chips · keybinds · last refresh).
4. Keyboard-first, mouse-welcome.
5. Empty states with personality.
6. Loading is honest (file progress via ParseProgress).
7. Refresh: silent ≤200 ms; pill toast otherwise.
8. Errors propose action.
9. Pricing transparency (math on `?`).
10. Privacy default-on (`show_prompts=False`).
11. Time-travel (`[`/`]`).
12. Comparable everywhere (Δ + sparkline per row).
13. No dead-ends (every row enter-actionable).
14. Themed, not painted (TCSS tokens).
15. No surprises (no writes outside parse_cache + caliper.toml).
16. First-run delight (welcome wizard celebrates what was found).

## 9. Keymap (global)

| Key | Action |
| --- | --- |
| `?` | toggle help |
| `g` / `Ctrl+P` | command palette |
| `q` / `Esc` | quit / back |
| `r` | refresh |
| `[` `]` | step interval ±1 |
| `Shift+[` `Shift+]` | step interval ×7 |
| `tab` `Shift+tab` | focus cycle |
| `enter` | open / apply |
| `/` | filter |
| `t` | cycle theme |
| `p` | toggle redact (confirm modal if turning off) |
| `e` | export current view to clipboard |
| `1..9` | jump to top-level screens |

Screen-local bindings cannot shadow these except inside an input field.

## 10. Testing strategy

- Pure helpers: `pytest`, ≥95% line + branch.
- Workers: run worker function bodies directly with the existing
  `tests/conftest.py` JSONL fixtures.
- Screens: `pytest-textual-snapshot` at 80×24, 120×40, 200×60.
- Pilot interactions: async pilot tests for every advertised key.
- Demo data: synthetic JSONL round-tripped through `load_usage`.
- Privacy invariant: with `show_prompts=False`, no real label string
  appears in any rendered tree.
- Total package coverage floor: ≥90%.

## 11. Performance budgets

- `caliper tui --demo` first paint ≤200 ms.
- `caliper tui` real load: first paint = LoadingOverlay ≤200 ms.
  Honest progress until data is ready.
- Refresh cycle ≤200 ms on demo data.
- Watchdog debounce: ≥2 s between refreshes.

## 12. Distribution

```bash
pip install 'caliper-ai[tui]'
caliper tui
# or
caliper tui --demo
```

When `textual` is not importable, `caliper tui` prints:

```
error: caliper tui needs the optional 'tui' extra.
Install with:  pip install 'caliper-ai[tui]'
```

Exit code 2 (same as other friendly CLI errors).

## 13. Definition of done

- All P0–P10 prerequisite commits merged and green.
- All T01–T27 Textual commits merged and green.
- `python -m build` wheel grep finds `.tcss` files.
- Coverage ≥90%.
- `caliper tui --demo` renders every screen with no exceptions.
- Existing CLI tests remain green; no CLI output changes.
- Snapshot suite stable across two CI runs.
- README + docs-site index updated with new section and one
  screencast SVG.
- CHANGELOG entry committed.

## 14. Non-goals

- Web dashboard.
- Telemetry of any kind.
- Daemon mode.
- Multi-user / role-based filters.
- New pricing source.
- Reflowing the JSON contract.

## 15. Reference: external APIs we depend on (verified Phase 4)

- `textual` 8.2.x: `App`, `Screen`, `ModalScreen`, `Widget`,
  `reactive`, `@work(thread=True, exclusive=True, group=..., exit_on_error=False)`,
  `Worker.is_cancelled`, `App.post_message`, `App.call_from_thread`,
  `App.suspend()` (POSIX), `App.register_theme`, `App.theme`,
  `App.ansi_color`, `App.push_screen / pop_screen / switch_screen`,
  `Provider` for command palette, `DataTable`, `Tree`, `TabbedContent`,
  `Input`, `Static`, `Footer`, `Header`.
- `watchdog` 4.x: `Observer` (platform-native), `PollingObserver`
  (portable fallback), `FileSystemEventHandler`.
- `pytest-textual-snapshot`: `snap_compare` fixture, syrupy-backed
  SVG snapshots, `--snapshot-update`.

---

**End of Phase 6.** Implementation proceeds in Phase 7 against this
document. Deviations require an entry in `08-post-audit.md` and a
fix in Phase 9.
