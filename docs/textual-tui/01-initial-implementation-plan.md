# Phase 1 — Initial Implementation Plan: Textual TUI for Caliper

**Status:** Draft (Phase 1) — anchor document.
**Date:** 2026-05-14
**Framework:** [Textual](https://github.com/Textualize/textual) (pure Python).
**Successor of:** the (discarded) Ink/Node TUI plan. Caliper stays a single-runtime, pip-installable, offline-by-default Python tool.
**Anchor rule:** Phases 2–9 refine but do not re-architect this plan. Research informs; the original direction holds.

---

## 0. Mission

Make Caliper feel like the most thoughtful CLI a developer has ever opened.

A user types `caliper tui`, and within ~150 ms the terminal becomes a calm,
opinionated workspace that answers the only questions that matter:

- "What did this PR cost?"
- "Am I about to blow my plan?"
- "Which model and tier is bleeding me?"
- "What changes if I move to Sonnet 4.6 priority?"

The tone is **a quiet operator on the other side of the line** — not a
dashboard, not a chatbot. Every screen reads like a sentence. Every shortcut
is consistent. Empty states have personality. Errors propose a next move.

We do not replace the existing Typer CLI. Every classic command (`overview`,
`daily`, `live`, `forecast`, etc.) keeps working unchanged. The Textual TUI
is an **opt-in immersive layer** that imports the same Python building blocks
the CLI already uses and wraps them in a coherent, navigable surface.

## 1. Context: what already exists in this repo

Verified by reading `src/caliper/` on 2026-05-14. Citations are
`module:line` so Phase 2 can re-verify quickly.

### 1.1 Package shape

- `pyproject.toml`: name `caliper-ai`, version `0.0.2`, entry point
  `caliper = "caliper.cli:app"`, `requires-python = ">=3.11"`, deps
  `platformdirs`, `rich>=13.7`, `typer>=0.12`. Optional extra `prom`.
  We will add a new optional extra `tui`.
- `src/caliper/` (≈140 KB Python): 30+ modules, all pure-Python, no network.
- Test surface: `tests/` with ≈40 files, all run by `uv run pytest` (369
  currently green on this branch).

### 1.2 CLI command surface (Typer)

`cli.py` (3,518 lines) declares one root `app` and six grouped sub-apps:

| Group | Commands |
| --- | --- |
| root | `overview` (default), `daily`, `weekly`, `monthly`, `session`, `blocks`, `project`, `models`, `evidence`, `limits`, `insights`, `tail`, `doctor`, `init`, `forecast`, `compare`, `pr`, `commit`, `live`, `whatif` |
| `rates` | `show`, `refresh`, `catalog` |
| `vendors` | `list` |
| `taxonomy` | `show` |
| `schema` | `export`, `validate` |
| `export` | `prometheus`, `grafana`, `receipt` |
| `budgets` | `check` |

Every grouped command supports `--format table|json|csv|markdown` and JSON
output is enveloped (`{"caliper": {...}, "...": ...}`).

### 1.3 Building blocks the TUI will reuse verbatim

All of these are **already pure functions or frozen dataclasses** — exactly
the shape Textual reactive code wants.

- `parser.load_usage(options) -> LoadResult` (`parser.py:593`). Reads
  Codex/Claude Code/Cursor/Aider JSONL via vendor adapters under
  `vendors/`. Cache via `parse_cache.py`.
- `pricing.load_rate_card(options) -> RateCard` + `RateCard.cost_for(usage,
  model, tier)`.
- `aggregation.aggregate_total / aggregate_daily / aggregate_weekly /
  aggregate_monthly / aggregate_sessions / aggregate_projects /
  aggregate_model_mode / aggregate_vendors / aggregate_overview_windows`
  (`aggregation.py:131–325`).
- `windows.compute_window_state` (`windows.py:68`) — primary/secondary
  credit windows, burn rate, ETA-to-100 used by `caliper limits` and the
  Rich live view.
- `forecasts.project` (`forecasts.py:55`) — linear + EWMA projection with
  ±1σ band and optional days-to-cap.
- `intervals.parse_interval` (`intervals.py:43`) — `"last 7 days"`,
  `"previous 7 days"`, `"this week"`, ISO ranges. Already powers
  `caliper compare --interval`.
- `scenarios.build_whatif_report` (`scenarios.py:263`) — pure cost
  re-simulation across `--tier` / `--model` swaps.
- `budgets.evaluate` (`budgets.py:54`) — already returns `BudgetAlert`
  records with severity and used-percent.
- `insights.build_insights` (`insights.py:23`) — humanized prose feed
  (cache reuse, tier confidence, project concentration, daily
  acceleration). Perfect Textual feed material.
- `health.build_health_report` (`health.py:57`) — doctor checks with
  status (`ok|warn|fail`). Perfect Textual list material.
- `live.collect_frame(options, now)` (`live.py:63`) — already produces a
  single `LiveFrame` snapshot suitable for re-rendering every tick.
- `output.with_caliper_envelope`, `humanize.format_int`,
  `humanize.redact` — same formatters used by tables/JSON today.

### 1.4 Existing Rich TUI (`caliper live`)

`live.py` already runs a Rich `Live` + `Layout` loop:

- Pulls `collect_frame(options)` every 2 s.
- Three panels (Usage / Primary 5h / Secondary weekly), one header line.
- Keys: `q` quit, `?` help, `r` refresh, `p` pause.
- Handles SIGINT, isatty checks, pause state, max-tick test hook.

We will **keep** this command. It becomes the "classic" zero-dependency
fallback when the optional `[tui]` extra is not installed. The new
`caliper tui` is the immersive workspace.

### 1.5 Invariants we will not break

Lifted from `CLAUDE.md` and re-verified against code:

1. **Offline by default.** No new network calls. The TUI never phones home.
2. **Frozen value objects.** `Usage`, `Rates`, `UsageEvent`,
   `LoadResult`, `RuntimeOptions`, `WindowState`, `LiveFrame`, `Interval`,
   `Projection`, `BudgetAlert`, `LongContextRule`, `ModelCard` stay
   frozen. Mutable Textual state lives only inside the App / Screens.
3. **Reasoning tokens cost output rate.** Long-context multipliers continue
   to apply via `RateCard.cost_for`. The TUI formats; it never re-computes.
4. **Tier precedence chain.** CLI override → tier-overrides JSON → logged
   tier → `~/.codex/config.toml` → assumed standard. The TUI surfaces the
   source, never re-derives it.
5. **Privacy by default.** `--show-prompts` is the only escape hatch.
   Session labels fall back to `session_id` when redaction is on.
6. **Severity-driven exit codes.** TUI sub-process invocations of doctor
   and budgets still exit 0 / 1 / 2.
7. **Frozen rate-card timestamp.** Doctor still warns >30d / fails >90d.

## 2. Why Textual, why not stay on Rich

Rich `Live` is already powering the current `caliper live`. We have hit
its ceiling for the experience we want to ship:

| Need | Rich `Live` | Textual |
| --- | --- | --- |
| Multiple navigable screens | manual | `Screen` stack with push/pop |
| Reactive state | hand-rolled poll loop | `reactive(...)` + watch methods |
| Sortable table with row focus, selection, sorting | possible but bespoke | `DataTable` widget |
| Modal dialogs (whatif sim, budget edit) | not really | `ModalScreen` |
| Command palette (`Ctrl+P`) | absent | built-in `command_palette` |
| Tabs / Tree / Tabs+Tree composition | manual layout | `Tabs`, `TabbedContent`, `Tree` |
| Async workers (parser, watcher) | thread + signal soup | `@work` decorator + `Worker` |
| Theming + light/dark | none | TCSS + `App.theme` |
| Mouse + scroll | limited | first-class |
| Snapshot testing | hard | `Pilot` + `pytest-textual-snapshot` |
| Accessibility (screen-reader hints) | none | `aria-label`-style hooks |

Textual is also **pure Python**, ships on PyPI, runs on macOS/Linux/Windows,
and is the same project that builds Rich, so visual continuity is free.
There is no Node, no second runtime, no IPC layer, no JSON wire contract.

Rich is not going away. The TUI imports Rich renderables directly when it
helps (e.g. `rich.text.Text`, sparkline strings, pricing tables) so we
reuse existing renderers without re-implementing them.

## 3. Architecture

```
+---------------------------------------------------------------+
| caliper tui  (single Python process)                          |
|                                                               |
|  +----------------+      +-----------------------------+      |
|  | Textual App    |      | Caliper core (unchanged)    |      |
|  |  Screens       |<---->|  parser.load_usage          |      |
|  |  Widgets       |      |  pricing.load_rate_card     |      |
|  |  Reactive vars |      |  aggregation.*              |      |
|  |  Workers       |      |  windows.compute_window     |      |
|  |  TCSS theme    |      |  forecasts.project          |      |
|  +----------------+      |  scenarios.build_whatif     |      |
|         |                |  budgets.evaluate           |      |
|         | watchdog       |  insights.build_insights    |      |
|         | (optional)     |  health.build_health_report |      |
|         v                +-----------------------------+      |
|  ~/.codex, ~/.config/claude-code, ~/.cursor, ~/.aider/        |
+---------------------------------------------------------------+
```

Key properties:

- **One Python process.** No subprocess, no JSON IPC, no wire version.
  Textual screens import core modules and pass `RuntimeOptions` directly.
- **Workers, not threads.** Heavy work (`load_usage`, `aggregate_*`,
  `build_whatif_report`) runs in Textual `@work(thread=True)` workers so
  the UI stays at 60 fps and is interruptible.
- **Reactive snapshot store.** A single `AppState` reactive holds the most
  recent `LoadResult`, `RateCard`, derived aggregates, computed at well-
  defined refresh points. Screens read from it; they never call
  `load_usage` themselves.
- **One shared `RuntimeOptions`.** Built once at launch the same way
  `cli.py` builds it (`_options(values)` → `RuntimeOptions`). User
  filters (interval, model, project, tier, redact, etc.) mutate a *copy*
  using `dataclasses.replace`.
- **Pure Python, pure formatting.** No new math in the TUI. We are
  literally rendering frozen dataclasses.

### 3.1 Module layout

```
src/caliper/tui/
  __init__.py        # public re-exports (CaliperApp, run_tui)
  app.py             # CaliperApp(App) + bindings + theme registration
  state.py           # AppState reactive, RefreshTrigger, ScopeFilter
  workers.py         # @work-wrapped data loaders + watchers
  theme.py           # tokens (colors, paddings), TCSS file loader
  screens/
    welcome.py       # first-run onboarding wizard (no logs found)
    home.py          # overview workspace (default screen)
    sessions.py      # session list + detail drawer
    projects.py      # project list + drilldown
    models.py        # model+tier breakdown + pricing transparency
    intervals.py     # daily/weekly/monthly tabs with sparkline + table
    limits.py        # primary/secondary windows + burn + ETA
    live.py          # Textual port of the Rich live view
    forecast.py      # linear + EWMA, days-to-cap, ±1σ band
    whatif.py        # tier/model swap modal + diff cards
    budgets.py       # budget gauges + breach toast feed
    insights.py      # humanized prose feed
    doctor.py        # health checks + actionable fix buttons
    receipt.py       # export-to-clipboard receipt + share
    help.py          # keymap + first-tour overlay
  widgets/
    cost_card.py     # number + delta + sparkline + scope chip
    sparkline.py     # thin wrapper around live._sparkline
    window_panel.py  # WindowState renderer, alarm at 80%
    budget_gauge.py  # progress bar + severity hue
    scope_chips.py   # interval/project/model filters, removable
    pricing_hover.py # tooltip-style explainer (long-context math)
    notice.py        # toast / status pill with icon
    onboarding_step.py
  tcss/
    base.tcss        # tokens, typography, spacing
    dark.tcss
    light.tcss
  fixtures/
    demo_data.py     # synthetic LoadResult for tests + screenshots
```

Public entry point: `caliper.tui.run_tui(options: RuntimeOptions)` invoked
from `cli.py` by the new `caliper tui` command.

### 3.2 Data flow

```
                       launch
                          v
+----------+    +-----------------------+    +--------------+
| CLI args | -> | RuntimeOptions (frozen)| -> | CaliperApp   |
+----------+    +-----------------------+    +--------------+
                                                    |
                                                    v
                                          spawn Worker: load_usage
                                                    |
                                                    v
                                          AppState.load_result   <---+
                                          AppState.rate_card         |
                                                    |                |
                                                    v                |
                                          recompute aggregates       |
                                                    |                |
                                                    v                |
                                          screens re-render          |
                                                                     |
                                  +--- user changes scope/interval --+
                                  |
                                  +--- watcher tick (live screen)   --+
                                  |
                                  +--- "r" pressed                  --+
```

A single mediator method `AppState.refresh(reason: RefreshReason)` is the
*only* way to re-load. It cancels in-flight workers, spawns a new one,
and emits `AppState.Refreshed` on completion. This keeps the loading
spinner and "last refreshed Xs ago" indicator honest.

### 3.3 Worker model

| Worker | Trigger | Output | Notes |
| --- | --- | --- | --- |
| `load_usage_worker` | launch, `r`, scope change | `LoadResult` | Long. Shows centered "Reading sessions…" overlay with file count progress. |
| `rate_card_worker` | launch, `rates refresh` | `RateCard` | Fast. Pure. |
| `aggregate_worker` | after `load_usage` resolves | `dict[str, Aggregate]` | CPU-bound but quick; we still run in a thread to keep the UI smooth on huge logs. |
| `whatif_worker` | modal apply | `WhatIfReport` | Pure math, sub-50ms typical. |
| `health_worker` | open Doctor | `list[HealthCheck]` | Includes IO. |
| `watchdog_worker` (optional) | Live screen entered | filesystem events | `watchdog` optional dep; falls back to polling. |
| `cache_warmer_worker` | idle, after first render | rebuild `parse_cache` for unseen files | Low priority. |

All workers `await asyncio.to_thread(...)` for IO-heavy work and use
`work(exclusive=True, group="data")` so duplicate triggers cancel
predecessors cleanly.

### 3.4 Reactive state shape

```python
@dataclass(frozen=True)
class Scope:
    interval: Interval          # default: last 30 days (matches CLI default for many commands)
    project: str | None = None
    model: str | None = None
    vendor: str | None = None
    tier: str | None = None
    redact: bool = True         # respect privacy invariant
    show_dollars: bool = True   # both shown; user can hide one

@dataclass(frozen=True)
class AppSnapshot:
    options: RuntimeOptions
    scope: Scope
    load_result: LoadResult | None
    rate_card: RateCard | None
    daily: list[Aggregate]
    weekly: list[Aggregate]
    monthly: list[Aggregate]
    sessions: list[Aggregate]
    projects: list[Aggregate]
    models: list[Aggregate]
    overview_windows: list[Aggregate]
    overview_total: Aggregate | None
    insights: list[Insight]
    budget_alerts: list[BudgetAlert]
    primary_window: WindowState
    secondary_window: WindowState
    refresh_started_at: datetime
    refresh_completed_at: datetime | None
    refresh_error: str | None
```

`AppState` itself is a `Widget`-less object that *owns* an `AppSnapshot`
inside a `reactive(...)` slot on the `CaliperApp`. Screens subscribe via
`watch_state(...)`. No screen owns a copy.

### 3.5 Distribution

- Add `tui` extra to `pyproject.toml`:
  ```toml
  [project.optional-dependencies]
  prom = ["prometheus-client>=0.20"]
  tui  = ["textual>=0.85", "watchdog>=4.0"]
  ```
- `caliper tui` command:
  - If `textual` not importable → print friendly hint identical in tone
    to `prom_export.py` today: `caliper tui needs the optional 'tui'
    extra. Install with: pip install 'caliper-ai[tui]'`. Exit code 2.
  - Else `caliper.tui.run_tui(options)`.
- `pip install 'caliper-ai[tui]'` is the documented install line for the
  immersive experience. The classic CLI continues to work with a bare
  `pip install caliper-ai`.

## 4. UX pillars (the "make it perfect" list)

Every screen must satisfy these before it ships. Self-audit checklist.

1. **One question per screen.** Each screen has a single headline number
   answering one user question. Other content supports it.
2. **Sentences, not labels.** "$42.17 spent last 7 days, 12% above your
   30-day average" beats "Cost: $42.17 | 7d: +12%".
3. **Always-visible footer.** Three lines: scope chips · keybinds · last
   refresh. Same on every screen.
4. **Keyboard-first, mouse-welcome.** Every action has a binding; mouse
   clicks invoke the same intent.
5. **Empty states have personality.** When `LoadResult.events` is empty,
   say "Nothing parsed yet. Run a Codex session, or press `d` to load
   demo data."
6. **Loading is honest.** Show file count progress
   ("Reading 1,983 / 4,210 sessions…") sourced from
   `UsageLoadAccumulator`. Never a bare spinner.
7. **Refresh is instant or audible.** ≤200 ms → silent. >200 ms → bottom
   pill "Refreshing…" with elapsed seconds.
8. **Errors propose action.** Every error includes a `[Press 'd' to run
   doctor]` or `[Press 'i' to re-init]` hint.
9. **Pricing transparency.** Any cost cell `?` cycles to show
   tokens × rate = $X math, plus tier source.
10. **Privacy default-on.** `Scope.redact=True` is the default. Toggling
    off shows a one-time confirmation modal.
11. **Time-travel.** `[ ]` step interval backward/forward one period;
    `Shift+[ ]` jumps 7×. Always relative to the open screen.
12. **Comparable everywhere.** Each rollup row owns a Δ vs previous
    period and a sparkline. No "what does this number mean" moments.
13. **No dead-ends.** Every list item is `enter`-actionable to a detail
    screen, or `e` exports the row to clipboard as Markdown.
14. **Themed, not painted.** Three themes: `slate` (default dark),
    `parchment` (light), `colorblind`. TCSS tokens, no hardcoded hex.
15. **No surprises.** No background mutations to the user's filesystem
    other than `parse_cache` writes (already happens today).
16. **First-run delight.** On first launch the welcome screen runs a
    sub-second auto-detect of installed vendors and *celebrates* what it
    found ("Found Codex sessions across 14 days. 3 cache speedups
    already paid for themselves.") before showing the home screen.

## 5. Screen map

Numbered by typical navigation order. Every screen binds `?` (help), `g`
(go-to / command palette), `[`/`]` (time scroll), `r` (refresh), `q`
(quit). Screen-specific keys are listed inline.

### 5.1 Welcome `welcome.py` (first-run only, or `caliper tui --tour`)

Goal: turn the empty-state moment into a tour.

- Animated 4-step sequence:
  1. "Scanning your tools…" → vendor auto-detect bar fills.
  2. "Found Codex / Claude Code / Cursor / Aider" — chips light up.
  3. "Loaded N sessions across Y days, last activity Δ ago" —
     headline.
  4. "Press space to enter Caliper." Bottom: "Or press d for the demo."
- Edge case: no vendors found → step 2 explains how to use each tool
  and offers `i` to run `caliper init`.

### 5.2 Home `home.py` (default screen)

Goal: answer "what did I spend recently and is anything wrong?" in one
glance.

Layout (≥120 cols):

```
+-------------------------------------------------------------+
|  Last 7 days        $42.17  ▁▂▃▄▆▆▇  +12% vs prev week     |
|  Last 30 days     $173.45   ▂▂▃▂▄▃▄▃  -3% vs prev 30d      |
|  Last 90 days     $441.02   ▁▂▃▃▂▃▄▄  steady                |
+-------------------------------------------------------------+
|  Limits         Primary 5h  43%  ███▌      reset 02:18      |
|                 Weekly     71%  █████▊    reset Sun 00:00   |
+-------------------------------------------------------------+
|  Insights                                                   |
|   • Cache reuse saved $9.40 last 7 days.                    |
|   • 73% of spend was 'standard' tier — try priority for...  |
|   • You spent more last Thu than the prior 6 days combined. |
+-------------------------------------------------------------+
|  Recent sessions                                            |
|    14:02  pr/auth-redo     codex-5            $1.21         |
|    11:47  spike/parser     claude-sonnet-4-6  $0.84         |
|    ...                                                      |
+-------------------------------------------------------------+
```

Layout (<120 cols): same cards stacked vertically, sparklines shrink.

Source data:
- `aggregate_overview_windows` (already exists post-perf commit).
- `compute_window_state(primary)` and `(secondary)`.
- `build_insights(...)`.
- `aggregate_sessions` truncated to top 5.

Keys: `1..5` jump to {Daily, Sessions, Projects, Models, Limits},
`tab` cycles cards, `enter` opens whichever card is focused.

### 5.3 Daily / Weekly / Monthly `intervals.py`

A `TabbedContent` over the three aggregates. Each tab is a `DataTable`
with: date · events · credits · API $ · cache saved · top model. Header
row sticky, sortable on click or via `s`. Row enter → detail drawer.

Sparkline at the top spans the visible range. `[`/`]` step the visible
window.

### 5.4 Sessions `sessions.py`

`DataTable` of recent sessions (filterable). Columns: when · project ·
vendor · model · tier · tokens · $. `/` opens fuzzy filter input.
Row enter → drawer with full breakdown + `e` export receipt for that
single session.

Drawer reuses `_compat_session_id_json` shape so receipts stay
consistent with `caliper session --format json`.

### 5.5 Projects `projects.py`

`Tree` of `project → sessions`. Side panel shows aggregate for the
selected node. Useful for "where did my PR cost go?".

### 5.6 Models `models.py`

Bar list of models × tiers sorted by spend. Columns: model · tier ·
events · input · output · cache hit · cost. `enter` opens the
Pricing Transparency drawer (math expanded line by line):

```
codex-5  standard
  in       3,210,890 tok × $0.0050 / 1k = $16.05
  out        612,330 tok × $0.0150 / 1k = $9.18
  reasoning  146,000 tok × $0.0150 / 1k = $2.19
  cache hit  890,000 tok × $0.0010 / 1k = $0.89  (saved $3.56)
  long_context: NO
  tier source: logged
```

### 5.7 Limits `limits.py`

Two big window panels (primary 5h, secondary weekly) borrowed from
`live._window_panel` but reflowed for Textual. Adds:
- Plain-language burn rate ("at this rate, primary hits 100% in 3h18m").
- Mini sparkline of `RateLimitSample.primary_used_percent` over the
  last 12 hours, useful for noticing reset effects.

### 5.8 Live `live.py` (Textual)

Direct port of the Rich live experience as a Textual `Screen`.
Refresh every 2 s via the `watchdog_worker` (filesystem events) with a
poll fallback. Uses the same `LiveFrame` snapshots, just rendered with
Textual widgets.

Adds:
- A toast notification "Budget X at 80% (primary 5h window)" when a
  threshold flips. Sourced from `budgets.evaluate`.

### 5.9 Forecast `forecast.py`

Inputs: budget cap input field, alpha slider for EWMA. Outputs:
- Linear projection card + EWMA projection card + days-to-cap.
- Mini chart (Textual `Plot` if available, else block ASCII via `_sparkline`).
- Action: `b` opens a "save as budget" modal that round-trips to
  `caliper.toml` `[budgets]`.

### 5.10 What-If `whatif.py`

Modal screen launched from Models or Forecast.

Inputs: tier picker (`standard | priority | flex`), model picker (full
taxonomy), interval picker (`Interval` parser preview as you type).

Outputs: `WhatIfReport` rendered as side-by-side cards (current vs
hypothetical), highlighting cost delta with hue and ± dollars. Action:
`enter` apply, `esc` close, `c` copy report as Markdown.

### 5.11 Budgets `budgets.py`

Vertical list of budgets. Each as a `BudgetGauge` widget (progress bar
with severity hue: green/amber/red mapped to `severity_for`). Right side
shows "used / cap / period / source".

Action: `n` create budget (form modal), `e` edit budget, `d` delete with
confirm. Persisted to `caliper.toml` via existing `parse_budgets_table`
+ a new `serialize_budgets` (small new pure function we add in Phase 7).

### 5.12 Insights `insights.py`

Card-per-`Insight` feed sourced from `build_insights`. Each card has
title, body, severity dot, and where applicable a one-key action
("Press `m` to open Models filtered by 'priority'").

### 5.13 Doctor `doctor.py`

`build_health_report` → list of `HealthCheck` rows with status pill.
- Failing rows expose `f` "fix" action where we know how:
  - `rate_card_age > 90d` → action "Run `caliper rates refresh`".
  - `parse_cache stale` → action "Rebuild cache" (call existing helper).
  - `state_db unreadable` → guidance only (no auto-fix).
- Exits to home with a `[Doctor: 3 warnings]` chip in the footer.

### 5.14 Receipt `receipt.py`

`caliper export receipt` rendered inline. Pre-populates with the
current interval. `enter` copies to clipboard. `w` writes to file via
file picker.

### 5.15 Command Palette (system)

`Ctrl+P` opens Textual's built-in palette pre-populated with:
- "Go to Daily / Weekly / Monthly / Sessions / Projects / Models /
  Limits / Live / Forecast / Budgets / Insights / Doctor".
- "Refresh now", "Toggle redact", "Cycle theme", "Open
  caliper.toml in $EDITOR".

### 5.16 Help `help.py`

Two columns: keymap (from `App.BINDINGS`) and "what you can do here"
prose. Always reachable via `?`.

## 6. Widget map

All custom widgets are thin renderers over data we already have.

| Widget | Renders | Notes |
| --- | --- | --- |
| `CostCard` | `(headline, delta, sparkline, scope_chip)` | Tap target on Home. |
| `Sparkline` | `list[float]` → Unicode block string | Wraps `live._sparkline`. |
| `WindowPanel` | `WindowState` | Severity hue at 80/95%. |
| `BudgetGauge` | `BudgetAlert` | Reuses `severity_for`. |
| `ScopeChips` | `Scope` | Removable chips for interval/project/model/vendor/tier. `x` clears. |
| `PricingTransparency` | model row | Expanded math from `RateCard.cost_for`. |
| `Notice` | `(severity, text)` | Toast pill. |
| `OnboardingStep` | step ordinal + state | Welcome wizard cells. |
| `LoadingOverlay` | `UsageLoadAccumulator` | "Reading 1,983 / 4,210". |
| `TimeScrubber` | interval `[`/`]` | Footer-aware. |
| `ThemeBadge` | theme name | Cycles. |

Existing Rich renderers stay reusable: panels in Live screen embed
`rich.text.Text` and `rich.table.Table` via `Static(renderable)`.

## 7. Theme + TCSS

Three named themes; same token set, different palette.

```
$bg, $bg-elev, $surface
$fg, $fg-dim
$accent, $accent-fg
$ok, $warn, $fail
$chip-bg, $chip-fg
$border, $border-strong
```

Mappings:
- **slate** (default dark): warm dark gray base, indigo accent.
- **parchment** (light): off-white, ink, sienna accent.
- **colorblind**: removes red/green pair, uses blue/orange severity.

User-cycles with `t`. Persisted in `caliper.toml` under
`[tui] theme = "slate"`. Default to `slate`.

Typography: rely on terminal font; use weight/italic + spacing rather
than color to convey hierarchy. Avoid box-drawing where Textual's
container borders already do the job.

## 8. Keyboard map (global, screen-stable)

| Key | Action |
| --- | --- |
| `?` | toggle help overlay |
| `g` / `Ctrl+P` | command palette |
| `q` | quit (or close modal) |
| `r` | refresh (cancels in-flight worker) |
| `[` `]` | step interval backward / forward |
| `Shift+[` `Shift+]` | step interval × 7 |
| `tab` `shift+tab` | focus cycle |
| `enter` | open detail or apply |
| `esc` | back / cancel |
| `/` | filter (where applicable) |
| `t` | cycle theme |
| `p` | toggle redact (with confirm if turning off) |
| `e` | export current view as markdown to clipboard |
| `1..9` | jump to numbered top-level screen |

Conflict policy: screen-local bindings never shadow globals unless an
input field has focus.

## 9. Implementation phasing (commits)

Atomic, code-reviewable. Each is a single PR-shaped commit. Sequential
unless noted parallel-safe.

```
01 chore(tui): add textual + watchdog to optional [tui] extra
02 feat(tui): scaffold caliper.tui package + run_tui entry
03 feat(cli): add `caliper tui` command (with install hint)
04 feat(tui): app shell, theme registration, base TCSS
05 feat(tui): AppState + reactive snapshot + Scope dataclass
06 feat(tui): load_usage_worker + LoadingOverlay
07 feat(tui): screens/home.py with CostCard + Sparkline + Limits row
08 feat(tui): screens/intervals.py daily/weekly/monthly tabs
09 feat(tui): screens/sessions.py with filter, detail drawer
10 feat(tui): screens/projects.py tree + side panel
11 feat(tui): screens/models.py + PricingTransparency drawer
12 feat(tui): screens/limits.py + WindowPanel reflow
13 feat(tui): screens/live.py Textual port of Rich live
14 feat(tui): screens/forecast.py linear+EWMA + budget-save
15 feat(tui): screens/whatif.py modal
16 feat(tui): screens/budgets.py + caliper.toml round-trip
17 feat(tui): screens/insights.py
18 feat(tui): screens/doctor.py with fix actions
19 feat(tui): screens/receipt.py + clipboard
20 feat(tui): command palette wiring + 1..9 jumps
21 feat(tui): welcome / first-run wizard
22 feat(tui): scope chips + interval scrubber + redact toggle
23 feat(tui): themes (slate, parchment, colorblind)
24 feat(tui): watchdog fs events with poll fallback
25 test(tui): pilot snapshot suite for every screen
26 docs(tui): README, screencast, keymap reference
27 chore(tui): release notes + changelog
```

Atomic commits 04–24 can be reviewed individually; 25+ rolls together.

## 10. Testing strategy

Coverage floor stays at 90%. The TUI must pull its weight, not lower it.

1. **Pure logic** — Snapshots, scope filtering, time-stepping, theme
   resolution, watcher debounce: regular `pytest` against pure functions.
2. **Workers** — Run the worker bodies (`load_usage_worker.run(...)`) in
   isolation against the existing `tests/conftest.py` `write_session()`
   helper. No Textual needed.
3. **Screens** — `pytest-textual-snapshot` pilot tests for every
   screen at 80×24, 120×40, 200×60. Pin `Console` width like the
   existing Rich snapshot tests do (`test_live.py`).
4. **Pilot interactions** — async pilot tests for keymap behavior:
   `await pilot.press("d")` → assert active screen is `IntervalsScreen`.
5. **Demo data** — `tui/fixtures/demo_data.py` builds a deterministic
   `LoadResult` so screenshots are stable.
6. **Performance budget** — pilot test asserting launch → first paint
   under 200 ms on the demo dataset (skip on Windows CI if flaky).
7. **Privacy invariant test** — assert that with `redact=True`, no
   session label, project path, or first message appears anywhere in
   a rendered snapshot. Mirrors `tests/test_privacy_invariant.py`.
8. **Schema invariants** — receipt export from the TUI must match
   `tests/test_schema_export.py` for the same `RuntimeOptions`.

## 11. Risks + mitigations

| Risk | Mitigation |
| --- | --- |
| Textual API drift between versions | Pin to `textual>=0.85,<1` initially; track upstream changelog; lock in Phase 4 research. |
| Large logs (the user's `~/.claude` was 7.7 GB) slow first paint | Spawn `load_usage_worker` post-mount; show progressive overlay; surface `--vendors` filter from welcome screen. |
| `parse_cache` already gets stale → wrong numbers | Re-use existing freshness check; doctor screen surfaces it; manual `Rebuild cache` action. |
| Watchdog optional dep missing | Detect at import; fall back to 2 s poll on Live screen; no crash. |
| Terminal too narrow | Reflow rules in TCSS; minimum supported 80×24; "terminal too small" splash below that. |
| User on Windows ConPTY quirks | Textual already supports it; CI matrix retained for 3.11/3.12/3.13. Add a `nox` smoke job that does a single pilot snapshot on Windows. |
| Coverage drop | New code lives in pure helpers; only thin Screen layer is exempt; pilot snapshots count toward branch coverage. |
| Clipboard portability | Use `pyperclip` via optional `tui` extra (or fall back to printing the receipt and asking the user to copy). Decide in Phase 4 research. |
| First-run delight backfires when zero data | Welcome screen handles empty path explicitly with `caliper init` hint. |
| Theme contrast on default terminal palettes | Use Textual `Color` blending + `prefers-color-scheme` env hints; manual contrast audit in Phase 5. |
| Async deadlocks | Workers always `await asyncio.to_thread` for IO; never call blocking work in widgets. |
| Long-running whatif | Worker with progress overlay; user can `esc` to cancel. |

## 12. Edge cases / failure modes

- `~/.codex/state_5.sqlite` locked → catch `sqlite3.OperationalError`,
  doctor screen surfaces it, home renders cached aggregates if any.
- Empty `LoadResult.events` → home shows "Nothing parsed yet" with two
  CTAs: load demo data, run init.
- Mixed vendors with disparate model taxonomies → models screen groups
  by canonical taxonomy (`taxonomy.py`) and surfaces a `?` chip.
- Tier source = `assumed` for >50% events → home shows an amber pill
  "Tier confidence low — check Doctor".
- Pricing catalog missing for a model → cell shows `?` with hover
  explainer "No published rate; using fallback".
- Long context inflation → row badge `LC` with hover math.
- User pastes a giant project name into filter → clamp to 80 chars,
  show ellipsis.
- Terminal resize mid-render → Textual handles; pilot test covers it.
- Time zone changes mid-session (rare) → snapshot recompute uses
  `local_timezone()` like `live.py` does today.
- `RateLimitSample` missing → window panels show "—" not "0%".
- Watchdog event storm → debounce to 2 s minimum between refreshes.
- User's machine clock skew → doctor `check_clock_skew` already
  flags it; home shows an amber pill if `WarningSummary` non-empty.

## 13. Open questions for Phase 2 audit

These are explicit. Phase 2 must decide each.

1. Should `caliper tui` become the default when stdin is a TTY and the
   `tui` extra is installed? Or remain explicit? (Bias: explicit.)
2. Do we ship a `--no-watchdog` flag for users on filesystems where
   inotify is unreliable (NFS / sshfs / WSL)? (Bias: yes.)
3. Should the welcome wizard run once per machine (`caliper.toml` flag)
   or once per *project* directory? (Bias: per machine.)
4. Where does demo data live — bundled module or generated lazily?
   (Bias: generated in-memory from a seeded RNG.)
5. Clipboard library: `pyperclip` vs `pyclip` vs OSC52 escape only?
   (Bias: OSC52 with `pyperclip` fallback if the extra is installed.)
6. Should the TUI export Prometheus / Grafana receipts in-app or
   delegate to `caliper export ...`? (Bias: in-app delegation
   to the same render path.)
7. Do we open `$EDITOR` for `caliper.toml` from inside the TUI
   (suspending) or print the path? (Bias: suspend.)
8. Is `[tui]` extra a separate wheel size concern? (Textual is small —
   confirm in Phase 4.)
9. Snapshot framework choice: `pytest-textual-snapshot` is reasonable
   but adds a dep on git-tracked SVG artifacts. Acceptable? (Bias: yes,
   gated to a `tui` test extra.)
10. The "celebrate what we found" headline in Welcome — what tone
    is *too* much? Phase 2 to pin one canonical sentence.

## 14. Non-goals (guardrails)

The TUI is **not**:

- A web dashboard. No Astro, no Next, no API. The `docs-site/` Astro
  build remains the marketing site.
- A telemetry surface. No analytics, no usage counters.
- A model-selection assistant. Pricing transparency only.
- A replacement for Doctor. It is a *surface* for Doctor's existing
  checks.
- A multi-user app. Single-user, local-only, file-backed.
- A reflow of the JSON contract. The JSON schemas in `schemas.py` are
  the source of truth and we ride on them.
- A new pricing source. `pricing.py` + `pricing_catalog.py` continue
  to be the canonical rates.
- A long-running daemon. Quitting the TUI ends the process. No daemons,
  no launch hooks.

## 15. Definition of done

The TUI is "done" for Phase 7 when:

- `pip install 'caliper-ai[tui]'` puts the user one keystroke from the
  Home screen.
- All 16 screens listed above are reachable, themed, keyboard-driven,
  reflowed for ≥80 cols, mouse-friendly, and snapshot-tested.
- Coverage ≥90% across the package, including TUI helpers.
- Existing `caliper live`, `caliper overview`, `caliper export`, etc.
  remain unchanged in output and behaviour (regression-tested).
- Doctor, Budgets, Forecast, What-If, and Insights all render their
  existing dataclasses without re-deriving anything.
- README and docs-site index updated with one new section + screencast.
- A single `caliper tui --demo` run produces a coherent, narrated
  welcome → home → models → whatif → forecast → quit experience on a
  fresh machine with no real data.

---

**Anchor reaffirmed:** Phases 2 through 9 may refine, tighten, and
correct — never re-architect. The single-process pure-Python design,
the optional `tui` extra, the reactive `AppState` mediator, and the
16-screen map listed here are the load-bearing decisions.
