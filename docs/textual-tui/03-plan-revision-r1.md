# Phase 3 — Plan Revision (Round 1)

**Status:** Draft (Phase 3)
**Date:** 2026-05-14
**Anchor:** Phase 1 (`01-initial-implementation-plan.md`) remains the
architectural source of truth. This document records the **refinements
adopted from the Phase 2 audit** — same architecture, sharper edges.

If the contents of this document conflict with Phase 1, Phase 3 wins
**for the items listed below** and only for those items. Phase 1 wins
for everything else.

---

## 1. Decisions adopted (locked)

These move from "bias" / "open question" in Phase 1 to "decision" here.
Phase 4 research may refine the *mechanism*; the decision itself stays.

| ID | Decision |
| --- | --- |
| D1 | TUI load window = **last 90 days** (matches `caliper overview`). Active interval default = **last 7 days**. |
| D2 | `Scope = {interval, show_dollars, show_credits}`. `project`, `model`, `vendor`, `service_tier`, `show_prompts` stay on `RuntimeOptions`. Scope changes apply via `dataclasses.replace(options, ...)`. |
| D3 | What-If takes `days: int`; new `caliper.scenarios.days_for_interval(interval)` translates from `Interval`. |
| D5 | Promote `cli._compat_session_id_json` → `caliper.exporters.session_compat_json`. The TUI Receipt screen and `caliper session --format compat-json` share that single implementation. |
| D6 | Suspend-to-editor on POSIX (`App.suspend()`). On Windows, fall back to printing the resolved `caliper.toml` path with a copy-to-clipboard helper. |
| D7 | Clipboard order: **OSC52** primary, **pyperclip** fallback (only if installed as part of `[tui]`), **inline receipt + visual select hint** last. Never crash. |
| D8 | `caliper tui` is always opt-in. The default `caliper` (no args) keeps printing the table-formatted overview. Scripts piping `caliper` are unaffected. |
| D-new-1 | First-paint budget: **≤200 ms on demo data**, **≤2 s on real 90-day load** (overlay covers anything beyond 200 ms). |
| D-new-2 | TUI never writes to `~/.codex/`. Only writes: `~/.cache/caliper/parse_cache.sqlite` (already today) and `$XDG_CONFIG_HOME/caliper/caliper.toml` (or `--config <path>`) for theme/redact persistence. |
| D-new-3 | Wheel ships `.tcss` files. CI validates with `unzip -l dist/*.whl \| grep .tcss`. |

## 2. Refined `Scope`

Replacing Phase 1 §3.4. The `AppSnapshot` now reads:

```python
@dataclass(frozen=True)
class Scope:
    interval: Interval                # drives options.start / options.end
    show_dollars: bool = True
    show_credits: bool = True

@dataclass(frozen=True)
class AppSnapshot:
    options: RuntimeOptions            # filter facts live here
    scope: Scope                       # display-only facts live here
    load_result: LoadResult | None
    rate_card: RateCard | None
    overview_windows: list[Aggregate]
    overview_total: Aggregate | None
    daily:    list[Aggregate]
    weekly:   list[Aggregate]
    monthly:  list[Aggregate]
    sessions: list[Aggregate]
    projects: list[Aggregate]
    models:   list[Aggregate]
    insights: list[Insight]
    budget_alerts: list[BudgetAlert]
    primary_window:   WindowState
    secondary_window: WindowState
    health: list[HealthCheck] | None   # populated only when Doctor opens
    refresh_started_at:   datetime
    refresh_completed_at: datetime | None
    refresh_error: str | None
```

Mutating the scope (interval step, project filter, tier swap) always
goes through:

```python
def apply_scope(state: AppSnapshot, *, interval=None, project=None,
                model=None, vendor=None, service_tier=None,
                show_prompts=None) -> AppSnapshot:
    options = state.options
    if interval is not None:
        options = replace(options, start=interval.start, end=interval.end)
    if project is not None:
        options = replace(options, project=project or None)
    if model is not None:
        options = replace(options, default_model=model)  # if applicable
    if vendor is not None:
        vendors = tuple(v.strip() for v in vendor.split(",")) if vendor else ("all",)
        options = replace(options, vendors=vendors)
    if service_tier is not None:
        options = replace(options, service_tier=service_tier)
    if show_prompts is not None:
        options = replace(options, show_prompts=show_prompts)
    scope = replace(state.scope, interval=interval or state.scope.interval)
    return replace(state, options=options, scope=scope,
                   load_result=None, refresh_completed_at=None,
                   refresh_error=None)
```

The mediator (Phase 1 §3.2) then re-spawns workers from the new
options. There is no separate "filter cache" — `RuntimeOptions` is
the cache key.

## 3. Pre-Textual prerequisite commits (the §H block)

These commits sit between Phase 1's `02` and Phase 1's `04`. Each is
atomic, ships with its own tests, and is reviewable on its own.

| # | Commit (conventional commit) | Why | Tests |
| --- | --- | --- | --- |
| P1 | `feat(parser): optional ParseProgress hook on load_usage` | enables honest loading overlay (C1) | new `test_parse_progress.py`; existing `test_parser.py` byte-identical with `progress=None` |
| P2 | `feat(insights): build_insights_from(*, total, projects, daily, ...)` | avoids re-aggregating in TUI (C2) | `test_insights.py` adds equality assertion vs. `build_insights` |
| P3 | `feat(health): public vendor_file_count + accept in build_health_report` | doctor screen needs it (C3) | `test_init_doctor.py` adds case |
| P4 | `feat(parse_cache): ParseCache.clear() with vacuum` | doctor "Rebuild cache" action (C4) | `test_parse_cache.py` adds clear+stat test |
| P5 | `feat(budgets): serialize_budgets() inverse of parse_budgets_table` | budgets round-trip (C5) | `test_budgets.py` adds property test |
| P6 | `feat(config): [tui] section + TuiConfig dataclass` | theme/redact persistence (C6) | `test_config.py` adds load+save case |
| P7 | `refactor(humanize): public sparkline() (moved from live._sparkline)` | TUI widget reuse (C7) | `test_humanize.py` adds case; existing `test_live.py` unaffected |
| P8 | `refactor(exporters): session_compat_json (was cli._compat_session_id_json)` | receipt parity (D5) | move helper, keep CLI behavior; `test_schema_export.py` unchanged |
| P9 | `feat(scenarios): days_for_interval(interval) helper` | whatif/interval shim (D3) | `test_intervals.py` extension |
| P10 | `chore(build): include src/caliper/tui/tcss/*.tcss in wheel + ci check` | distribution (C12, D-new-3) | new `test_wheel_data_files.py` shells out to `python -m build` (skip on Windows if slow) |

All ten land **before** the first Textual commit. After P10, the
existing test suite must still be green and CLI output unchanged.

## 4. Refined commit phasing (Phase 7 sketch)

Replacing Phase 1 §9. Numbering is contiguous. Atomic, reviewable.

```
P1 ..P10  prerequisites (above)
T01  chore(tui): add textual + watchdog to optional [tui] extra
T02  feat(tui): scaffold caliper.tui package + run_tui entry
T03  feat(cli): add `caliper tui` (install hint + --demo, --vendors, --since, --until)
T04  feat(tui): app shell, theme registration, base TCSS
T05  feat(tui): AppSnapshot + reactive store + apply_scope mediator
T06  feat(tui): workers (load_usage_worker, rate_card_worker, aggregate_worker) + LoadingOverlay using ParseProgress
T07  feat(tui): widgets/sparkline + widgets/cost_card + widgets/window_panel
T08  feat(tui): screens/home Home (3-window overview + limits + insights + recent sessions)
T09  feat(tui): screens/intervals daily/weekly/monthly tabs + sortable DataTable
T10  feat(tui): screens/sessions filter + detail drawer (uses session_compat_json)
T11  feat(tui): screens/projects Tree + side panel
T12  feat(tui): screens/models + PricingTransparency drawer
T13  feat(tui): screens/limits Textual reflow of WindowPanel
T14  feat(tui): screens/live (Textual port of Rich Live; debounced watchdog/poll)
T15  feat(tui): screens/forecast linear+EWMA + save-as-budget
T16  feat(tui): screens/whatif modal (uses days_for_interval)
T17  feat(tui): screens/budgets gauges + caliper.toml round-trip via serialize_budgets
T18  feat(tui): screens/insights cards (uses build_insights_from)
T19  feat(tui): screens/doctor + fix actions (rebuild parse cache, refresh rates)
T20  feat(tui): screens/receipt clipboard (OSC52 / pyperclip / inline)
T21  feat(tui): command palette + 1..9 jumps + suspend-to-editor
T22  feat(tui): welcome wizard + first-run flag in [tui]
T23  feat(tui): scope chips + interval scrubber + redact toggle modal
T24  feat(tui): themes slate / parchment / colorblind + NO_COLOR fallback
T25  test(tui): pilot snapshots (80x24, 120x40, 200x60) + privacy invariant + keymap
T26  docs(tui): README section, screencast SVG, keymap reference
T27  chore(tui): release notes + CHANGELOG entry
```

Total: 10 prerequisite + 27 Textual commits = 37 commits in Phase 7.
Each is independently revertable.

## 5. Edge-case additions

Adding to Phase 1 §12 the eleven items from Phase 2 §E. Excerpting:

- `caliper tui --demo` short-circuits parser, mounts deterministic
  `LoadResult` from `caliper.tui.fixtures.demo_data`.
- `caliper tui --vendors codex,claude-code` accepts the same shape as
  CLI `--vendors`.
- `caliper tui --since X --until Y` sets the initial `Scope.interval`.
- Worker cancellation: each `@work(thread=True)` checks a shared
  `threading.Event` between vendor files; abort cleanly on Ctrl+C.
- `stdout` not a TTY → hard error "caliper tui requires an interactive
  terminal."
- `NO_COLOR=1` → switch to monochrome variant of the active theme.
- Single-vendor mode → Models screen hides vendor-irrelevant columns.
- Timezone change mid-session → Limits screen re-resolves `now`.
- 80×24 minimum → cramped layout review is a hard part of Phase 7
  review.
- Welcome wizard re-run guard via `[tui] show_demo_on_first_run`.

## 6. Test plan additions

Adopting Phase 2 §G verbatim. The TUI test directory layout:

```
tests/tui/
  __init__.py
  conftest.py                  # demo Pilot fixture, redacted snapshot helper
  test_tui_app_boot.py
  test_tui_workers.py
  test_tui_scope_step.py
  test_tui_themes.py
  test_tui_keymap.py
  test_tui_privacy.py
  test_tui_demo_mode.py
  test_tui_doctor_actions.py
  test_tui_clipboard.py
  snapshots/
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

Coverage rule (re-asserting Phase 1 §10 with sharper numbers):
- Pure helpers (workers, fixtures, scope mediator, sparkline,
  PricingTransparency formatting, theme resolver): **≥95% line +
  branch**.
- Screens (`screens/*.py`): **≥80% line**, **pilot tests carry
  behavioral coverage** for the un-covered branches.
- Total package coverage stays **≥90%** (the configured floor).

## 7. Risks re-weighted

| Risk | Phase 1 / 2 | Phase 3 disposition |
| --- | --- | --- |
| Textual API drift | high | pin in Phase 4 (`>=X.Y,<Z`); add a one-shot import test to CI |
| 7 GB log first paint | high | P1 progress callback + load-window default 90d clamp; LoadingOverlay is now load-bearing |
| `parse_cache` stale | medium | P4 + Doctor `f` action surfaces it |
| TCSS not in wheel | medium | P10 + CI grep |
| Clipboard portability | low | D7 layered fallback |
| $EDITOR suspend on Windows | low | D6 fallback |
| Coverage floor | low | TUI tests + pilot snapshots offset screen-layer dilution |
| Async deadlocks | low | workers always thread-bound; UI never blocks |
| Snapshot churn on Textual upgrade | new | pin snapshot dep at minor version; document refresh recipe in `tests/tui/snapshots/README.md` |

## 8. Items deliberately deferred

These are noted to prevent scope creep mid-Phase 7. Not built in this
round.

- **Plot widget** for forecast — the ASCII sparkline carries the load
  for now. Phase 8 revisits.
- **Multi-pane workspace** — single screen at a time keeps focus
  predictable. Revisit only if user research demands it.
- **Vim bindings** beyond `[`/`]` time-scrubbing and `j/k` row nav in
  DataTables.
- **`caliper tui --record` SVG export** — Textual supports it; we will
  add a docs-only invocation, not a first-class flag, in Phase 7.
- **In-app pricing-catalog edit** — pricing edits keep happening
  in code via Phase 1's "Rate-card maintenance" workflow. The TUI
  *shows* the catalog read-only.
- **Multi-tenant / role-based filters** — Caliper is single-user;
  this is a non-goal forever.

## 9. Definition-of-done updates

Adding to Phase 1 §15:

- All ten **prerequisite commits (P1–P10)** merged and green.
- `python -m build` produces a wheel containing every `.tcss` file
  under `caliper/tui/tcss/`.
- `caliper tui` aborts with a friendly hint when `[tui]` extras are
  missing.
- `caliper tui --demo` runs offline against the fixture and renders
  every screen without crashing.
- Snapshot suite stable across two consecutive runs on macOS, Linux,
  and Windows (CI matrix).
- `tests/tui/test_tui_privacy.py` proves no real label leaks under
  `show_prompts=False`.

---

**Anchor reaffirmed.** All Phase-1 load-bearing decisions stand:
single-process pure-Python, reactive `AppState` mediator, optional
`[tui]` extra, 16 screens, no network. Phase 3 only sharpens the
edges Phase 2 found dull.

Next: **Phase 4 — Industry standards research.** Pin Textual version,
verify worker semantics, validate distribution patterns, audit
accessibility and clipboard behavior across terminals — without
reopening any decision listed above.
