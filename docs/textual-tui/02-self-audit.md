# Phase 2 — Self-Audit: Textual TUI plan vs. code

**Status:** Draft (Phase 2)
**Date:** 2026-05-14
**Method:** re-read every claim in `01-initial-implementation-plan.md`
against `src/caliper/` and `tests/`. Findings are concrete: each is a
gap, ambiguity, or wrong assumption, paired with the smallest plan/code
edit that closes it.
**Anchor reminder:** findings refine the plan — they do not redesign it.

Severity legend:
- **BLOCKER** — cannot ship the plan as written without fixing.
- **GAP** — fixable with a small code or plan addition; not a blocker.
- **AMBIGUITY** — plan reads fine, but two implementers might diverge.
- **NIT** — minor wording or doc-only cleanup.

---

## A. Public APIs the plan banks on — verification matrix

For each pure function the TUI imports, I re-verified the signature and
flagged anything the plan claims that the code does not provide.

| Plan claim | Code reality | Verdict |
| --- | --- | --- |
| `parser.load_usage(options) -> LoadResult` | `parser.py:593` matches. | ✅ |
| `pricing.load_rate_card(options) -> RateCard` | `pricing.py:587` matches. | ✅ |
| `RateCard.cost_for(usage, model, service_tier) -> (CostTotals, long_context, unknown_model)` | `pricing.py:349` matches. | ✅ |
| `aggregation.aggregate_overview_windows(...)` | New helper in `aggregation.py:143` (this branch). | ✅ |
| `aggregation.aggregate_sessions/projects/model_mode/vendors` | All present (`aggregation.py:272–325`). | ✅ |
| `windows.compute_window_state(samples, now, which)` | `windows.py:68`. Returns `WindowState`. | ✅ |
| `forecasts.project(daily_values, ...)` | `forecasts.py:55`. | ✅ |
| `scenarios.build_whatif_report(result, options, rate_card, *, days, tier, model)` | `scenarios.py:263`. Plan implied "interval picker → whatif" but the function takes `days: int`, **not an `Interval`**. | **GAP** |
| `budgets.evaluate(budgets, usage) -> list[BudgetAlert]` | `budgets.py:54`. | ✅ |
| `budgets.parse_budgets_table(table) -> list[Budget]` | `budgets.py:134`. Inverse `serialize_budgets` does **not** exist. Plan flagged this as a small Phase 7 add. | confirmed GAP, plan already accepts it |
| `insights.build_insights(result, options, rate_card=None) -> list[Insight]` | `insights.py:23`. Internally recomputes `aggregate_total/projects/daily` even when caller already has them. | **GAP** (mild perf, see §C2) |
| `health.build_health_report(*, options, session_file_count, result)` | `health.py:57` — **keyword-only `session_file_count` is required**. Plan didn't mention how the TUI obtains it. | **GAP** |
| `live.collect_frame(options, now)` | `live.py:63`. Snapshot is fine to reuse from the new Live screen. | ✅ |
| `intervals.parse_interval(expression, now) -> Interval(start, end, label)` | `intervals.py:43`. **Three** fields, plan only showed two. | NIT (plan wording) |
| `output.with_caliper_envelope` | exists; receipt screen will reuse. | ✅ |
| `_compat_session_id_json` for session-receipt parity | `cli.py:564`, currently `_private`. | **AMBIGUITY** (see §D5) |

## B. Frozen-dataclass invariants — re-verified

The plan promised "mutable Textual state lives only inside the App /
Screens." Re-reading `models.py`:

| Type | Frozen? | Notes for TUI |
| --- | --- | --- |
| `Usage` | `@dataclass(frozen=True, init=False)` (`models.py:59`) | Constructed via `Usage.from_dict` or similar helper. Demo-data fixture must use the public construction path; TUI cannot just `Usage(...)`. |
| `Rates` | `@dataclass(frozen=True, init=False)` (`models.py:143`) | Same caveat. |
| `RuntimeOptions` | `@dataclass(frozen=True)` (`models.py:199`) | `dataclasses.replace(options, start=..., end=...)` is safe for scope changes. ✅ |
| `UsageEvent` | frozen (`models.py:263`) | Safe. |
| `RateLimitSample` | frozen (`models.py:298`) | Safe. |
| `Aggregate` | `@dataclass` plain (`models.py:488`) | **Mutable**. The plan's `AppSnapshot` will hold lists of `Aggregate` — never share one list across threads; build fresh per refresh. **GAP** to document. |
| `LoadResult` | frozen (`models.py:629`) | Safe. |
| `Interval` | frozen (`intervals.py:13`) | Safe. |
| `LiveFrame` | frozen (`live.py:34`) | Safe. |
| `Insight` | frozen (`insights.py:15`) | Safe. |
| `WindowState` | frozen (`windows.py:17`) | Safe. |
| `Projection` | frozen (`forecasts.py:17`) | Safe. |
| `Budget` / `BudgetAlert` | frozen (`budgets.py:28`/`:39`) | Safe. |

## C. Concrete gaps that block end-to-end development

### C1. `load_usage` has no progress callback

**Plan claim (UX pillar §6):** "Show file count progress
('Reading 1,983 / 4,210 sessions…') sourced from `UsageLoadAccumulator`."

**Reality:** `parser.load_usage` and the vendor adapters do not accept a
progress callback. `UsageLoadAccumulator` lives inside the load and is
not surfaced.

**Severity:** BLOCKER for the promised UX.

**Smallest fix (Phase 7 prep):**
1. Add a `progress: ParseProgress | None = None` keyword to `load_usage`
   and to each vendor adapter (`codex.py`, `claude_code.py`,
   `cursor/...`, `aider.py`).
2. `ParseProgress` is a frozen dataclass + `Protocol`:
   ```python
   class ParseProgress(Protocol):
       def starting(self, total_files: int) -> None: ...
       def file_done(self, path: Path) -> None: ...
       def cache_hit(self, path: Path) -> None: ...
       def finished(self) -> None: ...
   ```
3. CLI path supplies `None` → no behavior change. TUI supplies a
   `TextualParseProgress` that posts events to the running `App` via
   `app.call_from_thread(...)`.
4. New unit test asserts CLI output is byte-identical with/without the
   parameter at default.

This change is small but real; it must be a numbered commit between
`02 feat(tui): scaffold` and `06 feat(tui): load_usage_worker`.

### C2. `build_insights` re-aggregates

**Plan claim:** TUI never re-derives from `LoadResult`; it formats.

**Reality:** `build_insights` internally calls `aggregate_total`,
`aggregate_projects`, `aggregate_daily` (`insights.py:29–31`). The TUI
already builds these for the Home screen.

**Severity:** GAP (mild). Insights are cheap, but on a fresh 90-day
load this is three extra passes.

**Smallest fix:** introduce a sibling
`build_insights_from(*, total, projects, daily, result, rate_card)` that
takes pre-built aggregates. Keep `build_insights(result, options, ...)`
as a wrapper for the CLI to stay byte-identical. New unit test pins
that wrapper output equals `build_insights_from(...)` output for the
same inputs.

### C3. `health.build_health_report(*, session_file_count, ...)` requires a file count

**Plan claim:** TUI opens Doctor screen and renders checks.

**Reality:** the function requires the *session_file_count* keyword. CLI
gets this from `_discovered_vendor_file_count(options)` at `cli.py:1544`.

**Severity:** GAP.

**Smallest fix:** promote `_discovered_vendor_file_count` to a public
helper in `health.py` (or `vendors/__init__.py`) so the TUI worker can
call it. Today it is `_private` in `cli.py`. New unit test pins its
output for a fixture session root.

### C4. `parse_cache.ParseCache` has no `clear()` / `rebuild()`

**Plan claim (screen 5.13 Doctor):** action "Rebuild cache" for the
`parse_cache stale` row.

**Reality:** `ParseCache` exposes `get`, `put`, `default()`, and a few
private helpers. No `clear`, `prune`, or `rebuild`. The CLI does not
offer a rebuild today either; users delete the file manually.

**Severity:** GAP.

**Smallest fix:** add a pure `clear(self) -> int` method that drops
all rows and `vacuum`s; return how many rows were removed. Bind a CLI
command `caliper rates refresh` already exists for pricing; mirror with
new `caliper init --rebuild-parse-cache` *or* a new `caliper doctor
--rebuild-parse-cache` flag. The TUI Doctor screen calls the same
helper. Mention in plan §15 (definition of done) that a public
`clear()` method now exists.

### C5. No `serialize_budgets` (plan already flagged)

**Plan claim:** Budgets screen round-trips through `caliper.toml`.

**Reality:** `parse_budgets_table` is one-way. The plan flagged the
small Phase 7 addition; re-confirming here.

**Severity:** GAP, planned.

**Smallest fix:** add `serialize_budgets(budgets) -> dict` in
`budgets.py` whose output round-trips through `parse_budgets_table`.
Property test: random valid `Budget` list → serialize → parse → equal.

### C6. Theme persistence needs `[tui]` section in `caliper.toml`

**Plan claim:** "User-cycles with `t`. Persisted in `caliper.toml`."

**Reality:** `config.load_config` returns the TOML as a plain dict.
`cfg(loaded, key, default)` only consults the top level and a few known
sections. There is no helper for namespaced sub-sections.

**Severity:** GAP.

**Smallest fix:** add `cfg_section(loaded, "tui")` → `dict`, and add a
small `TuiConfig` frozen dataclass:
```python
@dataclass(frozen=True)
class TuiConfig:
    theme: str = "slate"
    redact: bool = True
    show_demo_on_first_run: bool = True
    no_watchdog: bool = False
```
Builder reads from `loaded.get("tui", {})`, writer round-trips. New unit
tests next to `test_config.py`.

### C7. `Sparkline` helper is private

**Plan claim:** "Wraps `live._sparkline`."

**Reality:** `live._sparkline` is module-private. Reaching across with
`from caliper.live import _sparkline` works but is ugly.

**Severity:** NIT.

**Smallest fix:** promote it to `caliper.humanize.sparkline` (one-liner
move + re-export) before Phase 7 commit `07`. Replace the in-`live.py`
call with the public name. No behavior change.

### C8. Welcome-screen vendor auto-detect

**Plan claim:** Welcome screen "auto-detects installed vendors".

**Reality:** `vendors.__init__.py` already exposes
`vendor_summaries(options)` returning a list with paths + counts. ✅
Good — only the *progress overlay* nuance from §C1 was missing.

### C9. `aggregate_overview_windows` is brand new on this branch

**Plan claim:** Home screen uses `aggregate_overview_windows`.

**Reality:** It exists post the perf-refactor commit but has only one
test path today (CLI `overview`). The TUI uses it independently.

**Severity:** AMBIGUITY → low risk.

**Smallest fix:** add a parametrized unit test in
`tests/test_aggregation.py` covering the `detailed=False` and
`rate_card=None` branches before the TUI Home screen lands.

### C10. Watchdog optional dep — graceful import

**Plan claim:** "Watchdog optional dep missing → detect at import; fall
back to 2 s poll on Live screen."

**Reality:** We have no `try/except ImportError` shim today. Plan needs
a concrete shape:

```python
# caliper/tui/watch.py
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
```

`Live screen` calls `start_watching(...)` which dispatches polling if
`HAS_WATCHDOG is False`. Phase 4 will pin the version.

### C11. Worker exclusivity API

**Plan claim:** `@work(exclusive=True, group="data")`.

**Reality:** Plan-only — not verified against an installed Textual.
Phase 4 will pin to a Textual version that supports `exclusive=True` on
threaded workers (≥ 0.50 by changelog).

### C12. TCSS file packaging

**Plan claim:** TCSS files under `src/caliper/tui/tcss/`.

**Reality:** `pyproject.toml` uses hatchling. Non-`.py` data files
inside a package are included by default with hatchling **only if** the
package layout is right. Need to confirm `[tool.hatch.build.targets.wheel]`
glob includes the directory.

**Severity:** GAP.

**Smallest fix:** add an explicit include pattern:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/caliper"]
include = ["src/caliper/tui/tcss/*.tcss"]
```
Test by `python -m build` + `unzip -l dist/*.whl | grep tcss`.

### C13. Snapshot-test extra

**Plan claim:** `pytest-textual-snapshot` for screen tests.

**Reality:** No `[project.optional-dependencies] test` group exists
today; dev deps are under `[dependency-groups]` (uv-style) inside
`pyproject.toml`. Plan should clarify where the snapshot dep lives.

**Severity:** AMBIGUITY.

**Smallest fix:** keep snapshot dep inside `[dependency-groups.dev]`
to match existing convention. Pin `pytest-textual-snapshot` minor
version after Phase 4 research.

## D. Plan-only ambiguities that need a decision

### D1. Default interval

The plan says "default: last 30 days." Concrete decision the TUI
needs:
- CLI `overview` uses 90 days. CLI `daily` / `weekly` / `monthly` use
  90/180/365 respectively.
- The TUI Home screen *shows* 7/30/90 windows already (via
  `aggregate_overview_windows`).

**Decision (Phase 3 to bake in):** the TUI's *load window* is 90 days
(matches `overview`). The TUI's *active interval* defaults to "last 7
days" because that is the headline on Home. Scope-bar always reflects
the active interval, not the load window.

### D2. `Scope` overlap with `RuntimeOptions`

Plan §3.4 invents a `Scope` dataclass with `interval/project/model/
vendor/tier/redact/show_dollars`. But `RuntimeOptions` already has
`project`, `vendors`, `service_tier`, `show_prompts`. Holding both
risks drift.

**Decision (Phase 3):** `Scope` becomes:
```python
@dataclass(frozen=True)
class Scope:
    interval: Interval        # drives start/end
    show_dollars: bool = True
    show_credits: bool = True
```
Project/model/vendor/tier all live on the underlying `RuntimeOptions`
(via `dataclasses.replace`). Redact follows `options.show_prompts`.

### D3. `whatif` interval semantics

`build_whatif_report(*, days: int, ...)` takes days, but the TUI lets
the user pick an `Interval`. Translate `(interval.end - interval.start)`
into integer days. Caveat: the underlying `LoadResult` must already
cover that window — pass the appropriately scoped `LoadResult`. Add a
small helper `caliper.scenarios.days_for_interval(interval)` to
canonicalize.

### D4. Demo data fixture surface

`Usage` and `Rates` use `init=False` (custom `__init__`). Plan implied
free construction in the demo data module. Confirm via existing
tests:`tests/conftest.py` has `token_event(...)` and `write_session(...)`
helpers that emit JSONL → these are the *correct* construction path.

**Decision (Phase 3):** demo-data fixture writes synthetic JSONL into
an in-memory `Path` (or `tmp_path`) and round-trips through
`load_usage`. We never construct `UsageEvent` by hand from the TUI.

### D5. Receipt screen and `_compat_session_id_json`

Plan promised parity with the CLI session-receipt JSON. The function
is module-private. Options:
1. Promote to `caliper.exporters.session_compat_json`.
2. Re-render via the new TUI-side template.

**Decision (Phase 3):** option 1, because it preserves the schema-test
contract in `test_schema_export.py`.

### D6. "Open `caliper.toml` in $EDITOR" — suspend mode

Plan §13 Q7 biased "suspend." Textual's `App.suspend()` (or
`Driver.suspend`) returns control to the terminal, runs the editor,
resumes on exit. Confirm in Phase 4 that this works on Windows
ConPTY; if not, fall back to printing the path.

### D7. Clipboard

OSC52 escape works in tmux/iTerm2/Windows Terminal/Kitty but is
silently dropped by some terminals; `pyperclip` requires xclip/xsel
on Linux. **Decision (Phase 3):** OSC52 *primary*, `pyperclip` fallback
only if installed. Never crash if both fail; we instead show the
receipt inline with a "select and copy" hint.

### D8. `caliper tui` becoming default on TTY

Plan Q1 biased "explicit." Re-confirming: the CLI default remains
`overview`. `caliper tui` is always opt-in. (Reason: scripts piping
`caliper` rely on table output; an auto-TUI would break them.)

## E. Edge cases the plan did not name

These slipped through Phase 1. Adding to the canonical edge case list.

1. **`caliper tui --demo` flag** — Phase 1 implied a demo path but did
   not bind a flag. Decision: `caliper tui --demo` loads a deterministic
   in-memory fixture instead of `load_usage`.
2. **`caliper tui --vendor codex` etc.** — should accept the same
   `--vendors` CSV as the CLI so a user can start the TUI scoped.
3. **`caliper tui --since 2026-05-01 --until 2026-05-10`** — accept the
   same time-window flags so the TUI opens in that interval.
4. **`KeyboardInterrupt` during a worker** — Textual handles this for
   the UI, but our `@work(thread=True)` workers need a cancellation
   sentinel so they don't keep reading 7 GB of Claude history after the
   user hit Ctrl+C.
5. **SIGWINCH / terminal resize** — Textual handles it, but our custom
   widgets must use `Resize` event hooks where they cache layout
   (`Sparkline` width, `WindowPanel` bar width).
6. **`stdout` not a TTY** — `caliper tui` must hard-error early:
   `error: caliper tui requires an interactive terminal.`
7. **`--no-color` / `NO_COLOR=1`** — Textual respects but our TCSS
   theme uses color. Decision: detect, switch to high-contrast
   monochrome variant inside `slate.tcss`.
8. **Single-vendor mode** — when `vendors=["claude-code"]` is passed,
   the Models screen must omit Codex-only columns instead of showing
   empty cells.
9. **Sub-second clock drift** — `live.collect_frame` uses `now` from
   `local_timezone()`. If the user changes timezone mid-session, the
   Limits screen must re-resolve `now` per refresh.
10. **First-paint on 80×24** — must show *something* meaningful even at
    minimum size. Phase 7 review must cover the cramped layout.
11. **Welcome wizard already-onboarded** — read `[tui]
    show_demo_on_first_run = false` from `caliper.toml`. Plan-only,
    add explicit toggle.

## F. Risks the plan over- or under-stated

| Risk | Phase 1 weight | Re-weighted in Phase 2 |
| --- | --- | --- |
| Textual API drift | mentioned | **stays high** — pin in Phase 4 |
| 7 GB log set first-paint | mentioned | **stays high** — needs C1 (progress callback) |
| `parse_cache` stale numbers | mentioned | needs C4 (rebuild path) before Doctor screen is honest |
| Coverage drop | mentioned | OK, pure helpers + pilot snapshots cover it |
| Clipboard portability | flagged | needs D7 decision (now made) |
| Theme contrast | flagged | unchanged |
| Async deadlocks | mentioned | unchanged |
| Windows ConPTY | mentioned | needs CI smoke test |
| **New:** wheel does not ship TCSS | absent | C12 |
| **New:** $EDITOR suspend on Windows | absent | D6 |
| **New:** demo-data fixture construction | implicit | D4 |

## G. Tests the plan promised but did not enumerate

The plan said "snapshot every screen at 80×24, 120×40, 200×60" but did
not name the suite shape. Adding here so Phase 3 can produce a concrete
table:

| Test | Purpose | Location |
| --- | --- | --- |
| `test_tui_app_boot.py` | App mounts, default screen is Home, footer renders. | `tests/tui/` |
| `test_tui_workers.py` | `load_usage_worker` happy + cancelled + errored paths. | `tests/tui/` |
| `test_tui_scope_step.py` | `[`/`]` and `Shift+[`/`Shift+]` step intervals correctly per the parser. | `tests/tui/` |
| `test_tui_themes.py` | Each theme renders without color-class collisions; monochrome fallback under `NO_COLOR`. | `tests/tui/` |
| `test_tui_snapshot_*.py` | One file per screen, three resolutions each. | `tests/tui/snapshots/` |
| `test_tui_privacy.py` | With `show_prompts=False`, no real session label / first message string appears in any rendered tree. | `tests/tui/` |
| `test_tui_keymap.py` | Every advertised binding resolves to an action. | `tests/tui/` |
| `test_tui_demo_mode.py` | `caliper tui --demo` boots without reading disk. | `tests/tui/` |
| `test_tui_doctor_actions.py` | Doctor fix actions invoke the right helper. | `tests/tui/` |
| `test_tui_clipboard.py` | OSC52 emit + `pyperclip` fallback paths. | `tests/tui/` |

## H. Commit phasing — adjustments

Phase 1 listed 27 commits. After this audit, three insertions are
needed before the first screen lands:

```
03a feat(parser): optional ParseProgress hook for load_usage
03b feat(insights): build_insights_from(...) using pre-built aggregates
03c chore(parse_cache): add ParseCache.clear() + vacuum
03d feat(health): public vendor_file_count + accept it in build_health_report (keep kwarg name)
03e feat(humanize): public sparkline(values) helper (move from live._sparkline)
03f feat(config): load + write [tui] section (TuiConfig dataclass)
03g feat(scenarios): days_for_interval helper for whatif
03h feat(exporters): promote session_compat_json (was _compat_session_id_json)
```

(Numbering will be resequenced in Phase 6's final plan; here they are
slotted between Phase 1's `03` and `04` to signal they precede the
Textual scaffolding so Phase 7 has clean prereqs.)

## I. Verdict

- The plan is implementable as drafted with the **eight prerequisite
  commits in §H** plus the **`Scope` simplification in §D2** and the
  **whatif/interval shim in §D3**.
- No re-architecture is necessary. The single-process pure-Python
  approach, the reactive `AppState` mediator, the 16-screen map, and
  the optional `tui` extra all hold.
- The biggest single risk is **C1 (progress callback)**, because the
  promised "honest loading" UX depends on it and it touches every
  vendor adapter. Doing it as the *first* atomic commit before the
  Textual scaffolding lands keeps the blast radius small.
- The second largest risk is **C12 (TCSS packaging)**, because a
  silent failure here means themes work in dev but not from PyPI.
  Add a wheel-content test to CI.

Phase 3 (plan revision r1) will fold this audit's decisions into a
re-anchored plan: same architecture, sharper edges.
