# Implementation Plan: Persona Overhaul — Caliper UI/UX in "Calm, Accountable Clarity"

## 1. Anchor

This document is the source of truth for the Caliper UI/UX overhaul. Voice
name: **Calm, Accountable Clarity**. Every copy string, every flag, every
screen described below is owned by this plan. If
`docs/textual-tui/06-final-plan.md` and this plan disagree on a screen, this
one wins on copy and visuals. The other one wins on architecture, dataflow,
and worker contracts. No new architecture is introduced here. No web UI. No
telemetry. No network. The classic CLI surface keeps working byte-identical
when invoked with `--format` or under a pipe.

## 2. What "premium UX in Caliper's voice" means

You don't have a dashboard problem. You have a question problem. Caliper
exists to answer the four questions that decide a budget meeting: what did
this PR cost, am I about to blow my plan, which model is bleeding me, what
changes if I switch tier or model. The UI must answer one of those in the
first three seconds on every screen. Decision up top, evidence below, next
step in the footer. No hype, no buzzwords, no decoration that does not move
the answer forward.

## 3. Persona quick-reference for engineers

| Voice rule (source) | UI pattern |
| --- | --- |
| Name the constraint (Q33, "Always #1") | Every header line names a window. "Last 7 days. 48,727 credits. $3,383." No "Welcome to Caliper". |
| Make the claim testable (Q33, "Always #2") | Every insight ends with a measurable next step. "Pin tier with `--tier anthropic-priority` and re-run to compare." |
| End with a decision and owner (Q33, "Always #3") | Every screen footer carries one action affordance. `[ d doctor · e export · r refresh ]`. Errors end with a hot key. |
| No hype, no big nouns (Q25) | Banned in copy: leverage, optimize, drive, enable, insights (the word — keep `Insight` only as the dataclass), powerful, seamless, robust, modern, premium (irony noted). |
| No em dashes, no semicolons (Q22) | Lint rule in the persona helper. CI grep blocks new occurrences in `src/caliper/render.py`, `src/caliper/tui/`, `README.md`. |
| Short sentences, one idea per line (Q16) | Insight bodies cap at 22 words. Card subtitles cap at 8 words. Tooltip bodies cap at 60 words. |
| The reader should feel smart (Q46) | Empty states explain what is missing and what to type next, not what we couldn't find. |
| Constraint-first opener (Q16) | Every panel headline is a number or a window, never a label. "Models" is a tab title. The headline inside is "62% of last week on `claude-opus-4.7`." |

## 4. Vendor surfacing

### Decision

Two-axis vendor model. Show both the **tool vendor** (the local source of
the log) and the **model vendor** (who built the model). They are not the
same. Claude Code is a tool from Anthropic that ran an Anthropic model.
Cursor is a tool from Anysphere that can route to Anthropic, OpenAI, or its
own Composer model. Conflating them lies.

- **Tool vendor** comes from `UsageEvent.vendor` and the registered
  `VendorParser.label` (`OpenAI Codex`, `Claude Code`, `Cursor`, `Aider`).
  This is already in the data.
- **Model vendor** is new. Derive it from a small lookup table keyed by
  `ModelCard.id` (or by model-name regex if the card is missing). Live in
  `src/caliper/pricing.py` next to `MODEL_CARDS` as
  `MODEL_VENDOR_BY_ID: dict[str, str]`. Canonical labels: `anthropic`,
  `openai`, `anysphere`, `google`, `mistral`, `unknown`.

### Three options considered

1. **Inline glyph + name.** `[A] claude-opus-4.7`. Compact, scannable.
   Loses information when colour is off and the glyph collapses.
2. **Grouped column.** Separate `Vendor` column on every table. Honest, but
   eats horizontal real estate at 80 cols and pushes the cost column
   off-screen.
3. **Two-line cell with vendor chip.** Model on line 1, lower-case vendor
   chip on line 2. Honest, fits 80 cols, reads aloud.

**Picked: option 3.** Use the chip in tables and on cards. Use option 1
(`[A]` prefix glyph) only inside the dense Models screen header strip where
vertical space is the constraint. The glyph map: `[A]nthropic`, `[O]penAI`,
`[C]ursor/Anysphere`, `[G]oogle`, `[?]` unknown. Glyph plus name on first
row, glyph alone on subsequent.

### Touch points

| File | Function or location | Change |
| --- | --- | --- |
| `src/caliper/pricing.py` | new `model_vendor(model: str) -> str` | Lookup table plus regex fallback. Returns `"unknown"` when not derivable. |
| `src/caliper/models.py` | `ModelBreakdown` | Add `model_vendor: str = "unknown"`. Populated by aggregation. |
| `src/caliper/aggregation.py` | `Aggregate._add_event_identity` and `ModelBreakdown.add_event` | Populate `model_vendor` from `model_vendor(event.model)`. Add `Aggregate.model_vendors: set[str]`. |
| `src/caliper/render.py` | `_usage_table`, `compact_models` | Replace single-line model cell with model + vendor chip. |
| `src/caliper/render.py` | `model_breakdown_to_dict`, `aggregate_to_dict` | Add `"model_vendor"` and `"model_vendors"` keys. JSON contract grows additively. |
| `src/caliper/tui/widgets/cost_card.py` | render | Add vendor chip row below model row. |
| `src/caliper/tui/screens/home.py` | `_render_recent`, `_render_insights` | Surface vendor on every model mention. |
| `src/caliper/tui/screens/models.py` (new) | replace stub | Two-pane: tool vendor on left, model vendor breakdown on right. |
| `src/caliper/cli.py` | `models` command | Show vendor column. Honour `--only` filter on both axes. |

### JSON contract addition (safe)

`model_breakdowns[*]` gains `"model_vendor"`. `aggregate_to_dict` gains
`"model_vendors"` and keeps existing `"vendors"` (tool vendors) untouched.
Snapshot tests pin both. No removals before 1.0.

## 5. Flag vocabulary

### Policy

- Every existing flag becomes an alias forever. No removals before 1.0.
- New primary flags are short, constraint-named, and appear first in `--help`.
- Help text for each primary flag ends with one sentence in voice. Example:
  "Pins the window. The rest is filtered against it."
- A `--classic` flag (alias `--no-tui`) forces the Rich/CLI render path
  when stdout is a TTY.

### Mapping table

| Old primary (kept as alias) | New primary | Help string (voice) |
| --- | --- | --- |
| `--lookback-days`, `--days` | `--days` | "Rolling day window. Anchored on `--until`." |
| `--window-start`, `--since` | `--since` | "Inclusive start. Date or ISO." |
| `--window-end`, `--until` | `--until` | "Exclusive end. Defaults to now." |
| `--grouping-timezone`, `--timezone` | `--tz` | "Grouping timezone. IANA or `local`." |
| `--codex-session-root`, `--session-root` | `--from-codex` | "Codex JSONL root. Read-only." |
| `--codex-state-db`, `--state-db` | `--codex-db` | "Codex state DB. Read-only." |
| `--codex-config-file`, `--codex-config` | `--codex-config` | "Codex config.toml path." |
| `--caliper-config-file`, `--config` | `--config` | "Caliper config TOML path." |
| `--pricing-estimation-mode`, `--pricing-mode` | `--pricing` | "`model` or `flat`. `model` is the truthful default." |
| `--pricing-catalog-source`, `--pricing-source` | `--rates-from` | "Pricing source. `auto`, `embedded`, `litellm`, `openrouter`, `portkey`, `codex`." |
| `--pricing-catalog-cache-ttl-hours`, `--pricing-cache-ttl-hours` | `--rates-ttl-h` | "Hours before a cached rate card goes stale." |
| `--codex-service-tier`, `--service-tier` | `--tier` | "Service-tier override. Use this when logs disagree with reality." |
| `--assumed-service-tier`, `--unknown-service-tier` | `--unknown-tier` | "Tier to assume when nothing else identifies one." |
| `--service-tier-overrides-file`, `--tier-overrides` | `--tier-map` | "JSON of per-session or per-path tier overrides." |
| `--rate-card-file`, `--rates-file` | `--rates` | "Local rate-card JSON. Pin to match an invoice." |
| `--disable-deduplication`, `--no-dedupe` | `--no-dedupe` | "Keep duplicate events. Honest, not preferred." |
| `--disable-parse-cache`, `--no-parse-cache` | `--no-cache` | "Bypass the sidecar parse cache." |
| `--fallback-model`, `--default-model` | `--assume-model` | "Model assumed when logs omit one." |
| `--include-sensitive-prompts`, `--show-prompts` | `--reveal` | "Show prompts and full labels. Off by default." |
| `--pricing-offline-only`, `--offline/--no-offline` | `--offline/--online` | "Network use is opt-in. `online` only affects `rates refresh`." |
| `--compact-output`, `--compact` | `--compact` | "Drop columns. Use when the terminal is narrow." |
| `--table-width`, `--width` | `--w` | "Force column width. Default follows terminal." |
| `--row-limit`, `--top`, `--top-threads` | `--top` | "Cap grouped rows. `0` means all." |
| `--rate-limit-sample-limit` | `--samples` | "Recent rate-limit samples kept in JSON output." |
| `--include-all-rate-limit-samples` | `--all-samples` | "Keep every sample. Bigger payload." |
| `--output-format`, `--format` | `--format` | "table, json, csv, markdown, compat-json." |
| `--output-file`, `--output` | `--out` | "Write to file. Pipes still work." |
| `--sort-order`, `--order` | `--order` | "asc or desc." |
| `--week-start-day`, `--start-of-week` | `--week-start` | "Day weekly reports start on." |
| `--project-filter`, `--project` | `--project` | "Filter by project path or label." |
| `--split-by-project-instance`, `--instances` | `--by-project` | "Split daily rows by project instance." |
| `--include-model-breakdown`, `--breakdown` | `--per-model` | "Show one row per model under each group." |
| `--vendor-cost-mode`, `--cost-mode` | `--cost-from` | "`auto`, `calculate`, `display`. Whose number to trust." |
| `--include-vendor`, `--vendor` | `--only` | "Filter by tool vendor (`codex`, `claude-code`, `cursor`, `aider`). Repeatable." |
| (new) | `--only-vendor` | "Filter by model vendor (`anthropic`, `openai`, `anysphere`). Repeatable." |
| (new) | `--classic`, `--no-tui` | "Force the classic Rich render even on a TTY." |

### Deprecation copy

`--help` keeps every old flag visible under a small `Aliases` section per
option group. Long form: "Aliases: `--lookback-days`. Both work. The short
form is canonical." No removal before 1.0.

## 6. Output style guide

A single design language across Rich and Textual. Every pattern below ships
with copy in voice.

### 6.1 Section header

```
Caliper · Last 7 days · 2026-05-07 to 2026-05-14
48,727 credits   $3,383   95,090 events
```

### 6.2 Footer (every screen)

```
[1 home] [2 daily] [3 sessions] [4 projects] [5 models] [6 limits] [7 forecast]
r refresh · / filter · ? help · q quit            updated 14:22
```

Implementation: Textual `Footer` subclass `CaliperFooter`. For classic
Rich, the last printed line of every report.

### 6.3 Table cell density

Two-line cells where two facts matter. Single-line everywhere else. Numbers
right-aligned, right-padded to a fixed-width currency column.

### 6.4 Severity glyphs

| Severity | Glyph | Colour | Mono fallback |
| --- | --- | --- | --- |
| ok | `·` | foreground | `·` |
| info | `i` | accent | `i` |
| warn | `!` | amber | `!` |
| fail | `x` | red | `x` |
| breach | `X` | red bold | `X` |

No emoji. Glyphs survive `NO_COLOR`.

### 6.5 Divider

A single `─` rule of `1fr` width above section headlines. Not above tables.

### 6.6 Decision pill

```
[ d run doctor ]   [ p pin tier ]   [ e export receipt ]
```

Textual `DecisionPill(Static)` widget; Rich path renders bracketed text.

### 6.7 Constraint chip

```
[ only: anthropic · since 2026-05-07 · tier: priority ]
```

### 6.8 Insight callout

```
You don't have a cost problem. You have a claude-opus-4.7 problem.
That model is 62% of last week's spend.
Try: caliper whatif --swap claude-opus-4.7=claude-sonnet-4.6
```

Three lines. Claim. Evidence. Next step. Never more.

### 6.9 Empty state

```
No sessions in this window.
Either the window is too tight, or the tool wrote no logs.
Try: caliper --days 30   ·   caliper doctor   ·   caliper tui --demo
```

### 6.10 Error message

```
error: rate card is 94 days old.
That breaks the 90-day fail threshold. Costs after 2026-02 may drift.
Fix: caliper rates refresh --online   ·   or pin with --rates ./rates.json
```

### 6.11 Progress overlay

One line per file done. No spinner-only output. `TextualParseProgress`
extends to print a one-line completion summary ("parsed 4 vendors, 18,742
events in 11.4s").

## 7. Textual-by-default policy

### Branching rule

When `caliper <command>` runs and all four conditions hold:

1. `sys.stdout.isatty()` is true,
2. `sys.stdin.isatty()` is true,
3. `--format` was not passed,
4. `--out` was not passed,

then read-only report commands (`overview` default, `daily`, `weekly`,
`monthly`, `session`, `project`, `models`, `limits`, `insights`, `doctor`,
`forecast`, `budgets check`) launch the Textual workspace scoped to that
command's scope. The Textual app receives a `scope_intent: ScopeIntent`
(new dataclass in `caliper.tui.state`) so it can pre-select the right
screen, the right window, and the right filters.

When any condition fails, the classic Rich path is byte-identical to today.
CI snapshot suite is the contract.

### Bypass

- `--classic` (alias `--no-tui`) forces Rich.
- `CALIPER_NO_TUI=1` in the environment forces Rich.
- `caliper export …` is never affected. Exports never open the TUI.
- `caliper budgets check` only opens the TUI when stdin is a TTY *and*
  `--watch` is passed. In CI it stays classic so the exit code remains the
  contract.

### Mutating commands

`caliper init`, `caliper rates refresh`, `caliper export receipt …` never
branch. They print and exit.

## 8. Theme system

### Four themes, named

| Theme id | Mood | Use |
| --- | --- | --- |
| `slate` | calm dark | default when terminal background is dark |
| `parchment` | calm light | default when terminal background is light or `NO_COLOR=1` is unset on a light TTY |
| `colorblind` | tritan-safe palette, accent shifts from amber to teal | accessibility default when `COLORBLIND=1` or user opts in |
| `mono` | foreground + dim foreground only | default under `NO_COLOR=1` |

### Palette tokens (TCSS variables)

```
$surface, $surface-2, $foreground, $foreground-dim, $accent, $accent-2,
$ok, $info, $warn, $fail, $breach, $rule
```

### TCSS location

`src/caliper/tui/tcss/{slate,parchment,colorblind,mono}.tcss` plus
`base.tcss`. Already wired by the existing build artifact rule.

### NO_COLOR

If `NO_COLOR` is set, force `mono` and disable ANSI bold colour. Explicit
override path in `CaliperApp.on_mount`.

### Persistence

Persist user theme to `[tui] theme = "slate"` in `.caliper.toml` via the
existing `TuiConfig` accessor. Cycle key `t` writes through.

## 9. Insight engine

### Scope enum

```python
class InsightScope(StrEnum):
    home = "home"
    daily = "daily"
    sessions = "sessions"
    projects = "projects"
    models = "models"
    limits = "limits"
    forecast = "forecast"
    budgets = "budgets"
    doctor = "doctor"
    receipt = "receipt"
```

### Builder signature

```python
def build_insights_for_scope(
    *,
    scope: InsightScope,
    result: LoadResult,
    rate_card: RateCard,
    total,
    projects,
    daily,
    models,
    windows,
    forecast,
    budgets,
) -> list[Insight]: ...
```

Existing `build_insights_from` keeps its current shape and becomes the
home-scope path.

### Insight dataclass extension

```python
@dataclass(frozen=True)
class Insight:
    severity: str          # ok | info | warn | fail | breach
    title: str
    detail: str
    action: str
    scope: str = "home"
    evidence: tuple[str, ...] = ()
    next_command: str = ""
```

### Twelve in-voice templates

1. **home — model concentration.** "You don't have a cost problem. You
   have a `{model}` problem. {share:.0%} of last week ran on it. Try:
   `caliper whatif --swap {model}={cheaper}`."
2. **home — cache health.** "{ratio:.0%} of input tokens came from cache.
   That saved {savings}. Stable prompts keep that working."
3. **daily — acceleration.** "Last 3 days average {after} credits. Prior 3
   days averaged {before}. The trend is up, not noisy. Test it:
   `caliper daily --days 7`."
4. **sessions — long session warning.** "One session ran {hours:.1f} hours
   and cost {cost}. If that was a stuck loop, kill it next time. `caliper
   session --id {sid}`."
5. **projects — concentration.** "`{project}` is {share:.0%} of credits.
   The next four projects together are less. Decide if that is the intent."
6. **models — tier inferred.** "{count:,} events used an inferred tier,
   not a logged one. Pin it with `--tier {best}` to sharpen the number."
7. **models — vendor mix.** "Spend split: Anthropic {a:.0%}, OpenAI
   {o:.0%}. Cursor routed {c:.0%}. If you have an enterprise contract on
   one side, this is the lever."
8. **limits — burn rate.** "Primary 5h window is {pct:.0%} used, burning
   at {rate}%/hr. ETA-to-100 is {eta}. Pause, or accept the throttle."
9. **forecast — days to cap.** "At the current 7-day rate you reach the
   {cap} budget in {days} days. Earlier if the trend keeps accelerating."
10. **budgets — about to breach.** "Weekly credits at {pct:.0%}. One more
    long session breaches it. Either raise the cap or stop the meeting."
11. **doctor — rate-card age.** "Rate card is {age_days} days old. Past 90
    it fails. Run `caliper rates refresh --online` or pin with `--rates`."
12. **receipt — incomplete pricing.** "{n} events are vendor-reported, {m}
    are estimated. The number is honest. The line items are not."

### Where templates live

`src/caliper/insights/templates.py`. Each template is a function
`template_x(*context) -> Insight | None`. Adding a new template means
adding a function and listing it in the scope dispatch dict.

## 10. Screen-by-screen plan

1. **Welcome.** First-run only. Copy: "Caliper. Local cost ledger for
   AI-assisted coding. We read the logs already on this machine. Nothing
   leaves." Three keymapped paths: `1 use my logs`, `2 try the demo`,
   `3 read the privacy claim`. No splash art.
2. **Home.** Three cost cards (7/30/90). Each card carries a model + vendor
   chip showing the top-spend model in that window. Two `WindowPanel`s. One
   insight callout (home scope). Recent sessions table with `Tool` and
   `Model` columns; vendor chip on the model.
3. **Intervals (Daily/Weekly/Monthly).** Tabs. `DataTable` rows show
   `Date · Top model · Vendor chip · Credits · API$ · Δ vs previous`.
   Insight slot at top: daily-acceleration template. Sort by any column.
   `Enter` opens a sparkline drawer for that row.
4. **Sessions.** Filter input on top, `DataTable` below, side drawer for
   selected session. Drawer shows tool vendor and model vendor explicitly.
   Insight: long-session template.
5. **Projects.** Tree with project on the left, side panel on the right
   showing model + vendor split. Insight: concentration template.
6. **Models.** Two-pane. Left pane: model rows with vendor chip. Right
   pane: tier breakdown and `PricingTransparency` drawer. Glyph + name
   format. Insight: vendor-mix template.
7. **Limits.** `render_limits` reflow in Textual. Insight: burn-rate
   template with ETA-to-100. Decision pill is informational; we cannot
   pause for the user.
8. **Live.** Watchdog-driven refresh. Header line names the watch path.
   Footer shows debounce. No insight in tail mode. Steady underline that
   pulses on event arrival.
9. **Forecast.** Linear + EWMA bands. Insight: days-to-cap template.
   `e` exports the projection. `s` saves as a budget.
10. **What-If.** Modal. Two pickers: from-model, to-model. Show delta in
    credits, dollars, and percent. Insight: "If the test holds, you save
    {amount}/week. The risk is {risk}." Risk is hard-coded per model pair.
11. **Budgets.** Gauges. Round-trip `caliper.toml`. Insight: breach
    template.
12. **Insights.** Card stack of all scope insights, grouped by severity.
    `Enter` jumps to the screen that produced the insight.
13. **Doctor.** Replaces the existing stub. Health checks with fix
    actions: rebuild parse cache, refresh rates, validate config. Insight:
    rate-card age template. Each check ends in a decision pill.
14. **Receipt.** Month picker, vendor chip on every row. Insight:
    incomplete-pricing template. Clipboard via OSC52.
15. **Help (`?`).** Persona-voice keymap reference.
16. **Command palette (`Ctrl+P`).** Provider lists all top-level commands
    plus scoped insights.

### Mouse and keyboard parity

Every action reachable by keyboard is reachable by mouse and vice versa.
Footer affordances are clickable in Textual.

### Accessibility per screen

WCAG AA contrast pass under every theme. No information conveyed by colour
alone (glyph + colour + label).

## 11. Edge cases and risks

- **Mixed vendors with overlapping model names.** `gpt-5.5` appears in
  OpenAI and (potentially) in Cursor-routed events. Model vendor lookup
  must be deterministic per `(vendor, model)` pair, not model alone.
  Mitigation: default to `unknown` on conflict and surface it in `doctor`.
- **Vendors with no JSONL today.** Copilot is a known unknown. Every
  vendor surface lists known sources even when zero events.
- **Insights when data is sparse.** Templates self-skip when their
  pre-conditions fail. The home insight slot accepts "no insight to
  surface" as a valid state and renders a one-line constraint chip.
- **First run.** Welcome screen runs only when `~/.caliper/state.json` is
  absent. After that it is reachable from the palette but not on launch.
- **NO_COLOR.** Mono theme forced. Glyphs survive. Snapshot suite includes
  a mono pass.
- **Narrow terminal (80 cols).** Tables drop the cached-tokens column
  first, then standard-credits, then events. Two-line vendor chip stays.
- **Large logs first paint.** `TextualParseProgress` already in place.
  First paint target stays at ≤200 ms with `--demo`. Real-load first paint
  shows the overlay, not blank.
- **Broken pipe under `--format`.** Catch `BrokenPipeError` in the JSON and
  CSV paths and exit 0. Test with `caliper daily --format json | head -n 1`.
- **JSON contract drift.** Adding `model_vendor` is additive. Snapshot the
  keys present today and add a pin test that fails when a key disappears.

## 12. Acceptance criteria

- [ ] Persona helper module `caliper.persona` exposes `voice_lint(text) ->
      list[str]`. CI runs it on every `*.py` string literal under
      `src/caliper/render.py`, `src/caliper/tui/`, `src/caliper/insights/`,
      and on `README.md`, `CHANGELOG.md`. Zero violations.
- [ ] `model_vendor("claude-opus-4.7") == "anthropic"`. Property test for
      every model in `MODEL_CARDS`.
- [ ] `aggregate_to_dict(row)["model_vendors"]` is a sorted list of strings.
- [ ] `caliper models --format json` includes `"model_vendor"` on every
      breakdown.
- [ ] `caliper daily` table prints the vendor chip under the model name.
      Pinned snapshot.
- [ ] `caliper daily | cat` prints classic Rich (TTY-off branch). Pinned
      snapshot.
- [ ] `caliper daily` in an interactive terminal opens the Textual
      Intervals screen scoped to daily.
- [ ] `caliper daily --classic` forces Rich even on a TTY.
- [ ] `CALIPER_NO_TUI=1 caliper` forces Rich.
- [ ] `caliper budgets check` in CI keeps exit codes 0/1/2 unchanged.
- [ ] Themes load in order: env > config > terminal probe. Snapshot per
      theme at 80×24 and 120×40.
- [ ] First paint ≤200 ms on `--demo` on the CI runner.
- [ ] Every screen renders one insight or one constraint chip explaining
      its absence.
- [ ] Every error message ends with a decision pill containing at least
      one runnable command.
- [ ] WCAG AA contrast pass for every theme against the default terminal
      palette in the snapshot test.
- [ ] `voice_lint` passes on every help string in `cli.py`.
- [ ] Doctor surfaces `model_vendor: unknown` events when present.

## 13. Commit phasing

Forty atomic commits. Each one ships its own tests and is independently
mergeable.

**Voice helpers (3)**
1. `feat(persona): voice_lint banned-words + structure checker`
2. `test(persona): pin banned-words across rendered help text`
3. `chore(persona): wire voice_lint into CI grep step`

**Vendor surfacing (5)**
4. `feat(pricing): model_vendor lookup + regex fallback + unit tests`
5. `feat(aggregation): populate model_vendor on Aggregate and ModelBreakdown`
6. `feat(render): vendor chip in classic table cells (additive)`
7. `feat(tui): vendor chip on CostCard and Home recent sessions`
8. `feat(output): add model_vendor to JSON payload (additive)`

**Flag vocabulary (4)**
9. `feat(cli): add new primary flag names alongside old aliases`
10. `feat(cli): --classic and --no-tui to force Rich`
11. `feat(cli): --only-vendor (model-vendor) filter`
12. `docs(cli): rewrite --help strings in voice + alias section`

**Output style guide (5)**
13. `feat(render): single header/footer pattern across classic reports`
14. `feat(render): decision pill + constraint chip in classic path`
15. `feat(tui): CaliperHeader + CaliperFooter widgets`
16. `feat(tui): DecisionPill + ConstraintChip widgets + TCSS`
17. `feat(render): voice-tuned empty-state and error templates`

**Themes (3)**
18. `feat(tui): slate/parchment/colorblind/mono TCSS palettes`
19. `feat(tui): theme probe + persistence in caliper.toml`
20. `feat(tui): NO_COLOR auto-switch + mono snapshot pass`

**Textual-by-default (3)**
21. `feat(cli): TTY branching policy + ScopeIntent dataclass`
22. `feat(tui): scope-aware launch from cli per command`
23. `test(cli): TTY-on and TTY-off snapshot matrix per report command`

**Insight engine (4)**
24. `feat(insights): InsightScope enum + Insight.scope/evidence/next_command`
25. `feat(insights): build_insights_for_scope dispatcher`
26. `feat(insights): twelve voice-tuned templates`
27. `test(insights): every template fires + every screen consumes one`

**Screens (8)**
28. `feat(tui): Welcome screen replace stub`
29. `feat(tui): Intervals screen replace stub`
30. `feat(tui): Sessions screen replace stub`
31. `feat(tui): Projects screen replace stub`
32. `feat(tui): Models screen with vendor split`
33. `feat(tui): Forecast and What-If screens`
34. `feat(tui): Budgets, Doctor, Receipt screens`
35. `feat(tui): Live, Insights, Help, command palette polish`

**Polish (3)**
36. `feat(render): BrokenPipeError handling in JSON/CSV paths`
37. `feat(tui): mouse parity for footer affordances`
38. `feat(tui): accessibility pass + WCAG AA snapshots`

**Docs and release (2)**
39. `docs(persona): README and CHANGELOG in voice + keymap reference`
40. `chore(release): 0.1.0 bump + release notes`

## 14. Open questions

1. **Model-vendor source of truth.** Picked a lookup table in `pricing.py`.
   Default: keep it there. Other option: a per-vendor parser hint. Pick one.
2. **`--only` collision.** Today `--only` is unused. Default: claim it for
   tool vendors and add `--only-vendor` for model vendors. Other option:
   `--from` (tool) and `--by` (model). Picking matters because scripts
   will copy these.
3. **Welcome on first run.** Default: show once, persist a flag, never
   again. Other option: always show on `caliper` with no args until the
   user explicitly dismisses. Pick one.
4. **TUI default for `caliper insights`.** Default: TUI on TTY. Other
   option: insights is the one report that stays classic by default
   because users pipe it to slack.
5. **Cursor model-vendor.** Cursor's "composer" model is theirs
   (Anysphere). Cursor-routed Anthropic and OpenAI calls are still
   Anthropic and OpenAI. Default: attribute model vendor by model id, not
   by tool vendor.
6. **Voice lint scope.** Default: enforce on all user-visible strings in
   `src/caliper/`. Block on CI. Other option: warn-only for the first
   release.
7. **`--classic` vs `--no-tui`.** Default: both work, `--classic` is
   canonical. Other option: pick one and deprecate the other in a single
   release.
8. **Receipt insight.** Default: surface "n estimated, m vendor-reported"
   inside the receipt. Other option: leave receipts strictly factual, no
   insight slot. Finance handoffs are sensitive to vibes.

## 15. Non-goals

- No web dashboard.
- No telemetry.
- No new pricing source.
- No JSON contract removals.
- No flag removals before 1.0.
- No daemon.
- No multi-user roles.
- No reflow of the aggregation hot path.
- No new optional extras. Textual is already core in 0.0.4.

## 16. Definition of done

- Every acceptance bullet in §12 is checked.
- Every existing CLI test stays green.
- `python -m build` wheel still bundles `.tcss` files.
- Coverage stays at or above the configured 90% floor.
- `caliper tui --demo` renders every screen without exceptions.
- `voice_lint` returns zero violations on user-facing strings.
- README and CHANGELOG read in voice. The Litmus Test from
  `VOICE_PROFILE_RAJDEEP.md` passes: a stranger would believe Rajdeep
  wrote it.

---

WAITING FOR CONFIRMATION. The implementation has not started. Reply
`proceed` to begin, `modify: ...` to change scope, or ask any of the open
questions.
