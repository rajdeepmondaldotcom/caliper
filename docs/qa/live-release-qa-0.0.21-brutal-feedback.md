# Caliper 0.0.21 Live Release QA - Brutal Feedback

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.21`
Git target checked: `a58bf96`, tag `v0.0.21`

## Verdict

Caliper 0.0.21 is not a broken release. The core CLI is real, fast, and
mostly scriptable. That is the good news.

It is not "perfect UI/UX" and it is not yet Show HN hardened. The biggest
problem is not parser correctness. The biggest problem is launch trust: the
docs-site Quickstart has a budget config that silently defines no budgets,
the TUI overpromises polish, and several outputs still look like an engineer
debug console instead of a product ready for hostile public scrutiny.

If this hits Hacker News today, the favorable thread is "useful local CLI,
rough edges." The unfavorable thread is "promising offline cost attribution,
but the docs and UI make me wonder what else is sloppy."

## Evidence Gathered

- Verified latest release identity through PyPI JSON
  (`https://pypi.org/pypi/caliper-ai/json`), PyPI simple index
  (`https://pypi.org/simple/caliper-ai/`), local git tag, and
  cache-bypassing `uvx --isolated --refresh --from caliper-ai caliper
  --version`. All resolved to `0.0.21`.
- Installed `caliper-ai==0.0.21` into a clean temp venv with Python 3.13.
- Ran 113 CLI scenarios across install/help/overview/grouped reports,
  exports, rates, schemas, budgets, git attribution, bad inputs, and edge
  formats.
- Parsed 31 JSON outputs and 20 CSV outputs successfully.
- Verified default JSON path redaction: no QA temp path or `/work/...` path
  leaked unless `--show-paths` was passed.
- Verified a truly empty machine path: `overview` exits 0 and shows an
  onboarding message.
- Ran Textual TUI test pilots at 80x24 and 120x40 in demo and fixture-backed
  modes, exported SVG screenshots for Home and numbered screens.
- Tested Prometheus both without the `[prom]` extra and with
  `caliper-ai[prom]==0.0.21`.

## Launch-Killer Findings

### P0 - Docs-site Quickstart gives a budget config that does not create budgets

Persona: LinkedIn engineering manager, FinOps reviewer, YC technical partner.

The docs-site Quickstart tells users to put this in `.caliper.toml`:

```toml
[budgets]
daily_credits = 25000
weekly_credits = 100000
monthly_api_dollars = 500
```

The live app expects keys like `daily_cost_usd`, `weekly_cost_usd`, and
`monthly_cost_usd`. When I copied the docs-site config into 0.0.21 and ran
`caliper budgets check`, the result was:

```text
No budgets defined. Add a [budgets] table to .caliper.toml. Example:
daily_cost_usd = 25.0.
```

Exit code was 0.

Brutal feedback: this is the kind of thing HN will not forgive. The product
claim is "gate CI on cost." The docs-site tells users to install a gate that
does not gate. A manager copying this into CI would think they are protected
while Caliper exits cleanly. That is worse than no docs.

### P1 - Empty first-run onboarding only says it checked Codex

Persona: Reddit first-time user, HN CLI pedant.

On a truly empty temp home with Codex, Claude, Cursor, and Aider roots
isolated, `caliper overview` prints:

```text
No AI coding usage logs found in the active window.

Checked:
- Codex sessions directory
- Codex state DB
```

The app supports Claude Code, Cursor, and Aider, but the first-run message
does not name them. A non-Codex user can reasonably conclude Caliper did not
even look for their tool.

Brutal feedback: the first-run path is the product. This message tells a
Claude/Cursor/Aider user, "you are not the target user," even though the
marketing says they are.

### P1 - Docs-site install and examples are stale relative to the README

Persona: HN drive-by installer.

The README now recommends:

```bash
uvx --isolated --from caliper-ai caliper
```

The docs-site still says:

```bash
uvx --from caliper-ai caliper
```

The docs-site landing page still shows the older "credits" sample output, and
the Quickstart budget keys are wrong. For launch, the docs-site and README
feel like two different products.

Brutal feedback: stale docs are a trust leak. A skeptical user will assume the
pricing model is equally stale.

## TUI / UI / UX Findings

### P1 - TUI navigation overpromises screens that are not reachable by documented keys

Persona: product-minded YC partner, terminal power user.

The README says the workspace includes What-If, Budgets, Insights, Doctor,
and Receipt. Number keys cover Home, Intervals, Sessions, Projects, Models,
Limits, Live, Forecast, and Doctor. There is no documented key path to
What-If, Budgets, Insights, or Receipt in the actual visible navigation.

The hidden `_SCREENS` map has those screens, but a real user should not need
to read source code to discover them.

Brutal feedback: this makes the TUI feel like a demo shell around the CLI,
not a workspace. A YC partner will ask "why is the TUI here if the real power
features are invisible?"

### P2 - `NO_COLOR=1` does not actually switch the TUI to monochrome

Persona: accessibility reviewer, terminal user.

Observed with `NO_COLOR=1` under Textual run-test:

```json
{
  "theme": "textual-dark",
  "tui_config_theme": "slate",
  "no_color": "1"
}
```

The code tries to map `monochrome` to `textual-ansi`, but the installed
Textual themes include `ansi-dark`, not `textual-ansi`. The exception is
suppressed, so the app silently stays dark.

Brutal feedback: don't claim terminal-respectful theming until `NO_COLOR`
actually changes the visual result.

### P2 - 80x24 TUI wraps and clips high-value labels

Persona: terminal user on a laptop split pane.

At 80x24, the Home screenshot splits "Last 30 days" awkwardly (`Last 30 da`
then `ys`) and clips the welcome tagline (`AI-assisted cod` then `ing.`).
The Doctor screen clips long paths at the edge.

Brutal feedback: the app is usable, but it is not polished. The exact audience
for a terminal product will test it in an 80-column pane and judge fast.

### P2 - Demo/Doctor TUI exposes absolute temp paths

Persona: HN privacy skeptic.

The demo Doctor screen shows paths like a system temp directory. Real Doctor
also shows absolute QA fixture paths. That may be intentional for a diagnostic
screen, but it clashes with the privacy-first product posture and the default
machine-readable redaction story.

Brutal feedback: a privacy skeptic screenshotting the TUI can make the product
look leakier than it is. Either mark Doctor as "local diagnostic paths shown"
or add a redacted mode.

### P2 - First-run `caliper tui --demo` starts with a welcome wall, not data

Persona: impatient Reddit user.

Fresh config opens `WelcomeScreen` first and requires space before reaching
the demo. The welcome copy is short and accurate, but the command name says
`--demo`; users expect to see the product immediately.

Brutal feedback: for a launch-day demo, one extra gate before the data costs
curiosity.

### P3 - Theme labels are product-specific, actual themes are Textual fallbacks

Persona: design-sensitive CLI user.

The app cycles `slate`, `parchment`, `colorblind`, `monochrome`, but those
names are not registered as visible Textual themes in the run-test
environment. The user mostly sees built-in Textual themes.

Brutal feedback: if the theme names are marketing language, the visuals need
to earn it.

## CLI / Output Findings

### P1 - Markdown and CSV expose unrounded percentage noise

Persona: finance user, HN CLI pedant.

Examples from live 0.0.21:

```text
667.3694581280788
-21.853624423610658
237.51552795031057
```

These appear in compare/what-if Markdown and CSV paths.

Brutal feedback: a finance-facing tool cannot dump Python-float-looking
percentages into Markdown receipts. It makes the money math look amateur even
when the math is probably fine.

### P2 - `statusline` is too long for an actual status line

Persona: shell prompt user.

Fixture-backed `statusline` output was 167 characters:

```text
aider-reported/standard | project backend-api | today $0.19 | 7d $0.23 | 5h 77% reset 59m ...
```

Brutal feedback: this is not a status line; it is a sentence. A prompt
integration needs a compact mode, hard max width, or fields users can disable.

### P2 - Multi-vendor table output is overwhelming even for six events

Persona: first-run user.

With only six controlled events across three vendors, `overview` printed one
table per vendor plus unified totals, producing 82 lines and 140-character
lines. `--compact --width 60` helped but still produced 160 lines and max
82-character lines.

Brutal feedback: the per-vendor split is useful, but the default makes a small
dataset look noisy. The first thing users see should be a summary, not a wall.

### P2 - Evidence wording can become too fatal for mixed-quality data

Persona: skeptical but interested HN user.

With five usable events and one unsupported pricing event, `evidence` and
`insights` said "Overall: unsupported" / "Accuracy is unsupported." That is
technically conservative, but it makes the entire report sound worthless.

Brutal feedback: if one row poisons the whole trust label, users will stop
reading. "Partial - 5 priced, 1 unsupported" is more truthful and less
self-sabotaging.

### P2 - `rates catalog` looks broken on fresh install

Persona: HN pricing skeptic.

Fresh install:

```text
Caliper - Pricing Catalog
pricing catalog cache unavailable: ... rates-fetched.json
no cached live pricing catalog. Run `caliper rates refresh --allow-network`.
```

JSON reports `"model_count": 0`; CSV is empty; Markdown says `_No data._`.
Meanwhile `rates show` has embedded rates.

Brutal feedback: a user checking pricing credibility may run `rates catalog`
and think the product shipped with no catalog. The distinction between
"embedded rate card" and "live fetched catalog cache" is too subtle.

### P3 - Export subcommands have inconsistent source flags

Persona: CLI pedant.

`export receipt` and `export prometheus` accept data-source flags. `export
grafana` does not, because it emits static dashboard JSON. That is technically
fine, but the command family feels inconsistent.

Brutal feedback: either make static exporters clearly static or accept and
ignore common source flags with a warning. Current behavior creates "why does
this subcommand reject the same flags?" friction.

### P3 - Prometheus exporter can print BrokenPipe tracebacks

Persona: ops user.

With `caliper-ai[prom]==0.0.21`, a short-timeout metrics client caused Python
`BrokenPipeError` tracebacks on stderr. A normal 10-second client retrieved
metrics successfully, so this is not a functional blocker.

Brutal feedback: operators hate noisy stack traces from normal network
behavior. Prometheus scrapers and probes can disconnect.

### P3 - `advise` can feel inert when `whatif` shows savings

Persona: Reddit skeptic, power user.

In the controlled fixture, `caliper whatif --tier standard` showed a lower
projected cost, while `caliper advise` returned:

```text
No suggestions for this window.
```

This may be intentional thresholding, but a real user will not know that. The
tool has enough information to show "there is a cheaper hypothetical" in one
command and no recommendation in another.

Brutal feedback: if advice is conservative, say why. Silent conservatism
looks like the advisor is broken.

## Privacy / Security Findings

### Pass - Machine-readable path redaction worked

Default JSON did not contain the QA temp root or fixture project paths. It did
contain `<redacted-path>`. Passing `--show-paths` restored the absolute paths.

### Pass - Prompt/title markers did not leak in tested outputs

Synthetic private markers in state DB titles and first messages did not appear
in captured CLI stdout.

### Concern - TUI diagnostic path display needs explicit framing

The TUI Doctor path display is not necessarily a vulnerability, but it is a
privacy perception issue. The product sells "offline/no upload/redacted." The
UI should tell users when local paths are intentionally visible.

## Persona Attacks

### YC partner

"This is a real wedge, but the product story is fragile. The CLI is stronger
than the interface. If the launch points users to docs where the budget gate
does not gate, I worry the founder is optimizing for shipping versions rather
than trust."

### YC technical partner

"The offline architecture is credible. I like JSON/CSV parseability and
redaction. I do not like stale docs and fatal evidence wording. A cost tool
must be boringly precise in labels."

### Hacker News privacy skeptic

"You say no upload and redaction. Fine. But then your TUI Doctor screenshots
show absolute paths and your docs are inconsistent. I will believe the code
more than the marketing, but the marketing is asking for skepticism."

### Hacker News CLI pedant

"Good command surface. Bad polish in outputs. Percentages with 15 decimals,
statusline too long, `rates catalog` empty on fresh install, command-family
flag inconsistencies. This feels like a useful 0.x tool, not a finished CLI."

### Reddit indie developer

"I can install it and get numbers. That part is good. But first-run empty
state only mentions Codex, and the TUI demo puts a welcome screen in front of
the data. Show me the money immediately."

### Reddit skeptic

"Why should I trust the bill math if one command says the catalog has 0 models
and another command has rates? Why does advice say nothing when what-if shows
savings? Feels like I need to know internals."

### LinkedIn engineering manager

"The budgets story is valuable. The docs-site config is a dealbreaker. I need
copy-paste CI snippets that cannot silently do nothing."

### FinOps/CFO reviewer

"Receipts are promising, but raw decimal noise and evidence labels need to be
boardroom-safe. I need 'partial with X unsupported' not 'unsupported' slapped
over mostly useful data."

### Security engineer

"The no-telemetry stance is strong. Dependency surface is reasonable. I want a
documented threat model for what the TUI intentionally displays, and I want
BrokenPipe tracebacks suppressed in long-running exporters."

### Accessibility / terminal user

"NO_COLOR does not work. 80-column layout is serviceable but not polished.
Theme names do not map to visible custom themes. This is not terminal-native
enough yet."

### OSS maintainer

"The codebase has tests and the CLI behavior is broad. The support burden will
come from docs drift, not from parser crashes. Fix docs before inviting HN."

### Power user

"The APIs are there. I can script it. But I will use JSON, not the TUI, until
navigation, width, and labels mature."

## What Worked Well

- `uvx --isolated --refresh --from caliper-ai caliper --version` resolved the
  correct release.
- Core command matrix ran quickly. Most commands completed in under 250 ms on
  the fixture.
- JSON and CSV outputs parsed cleanly.
- Friendly error handling worked for malformed config, bad rates JSON, bad
  tier map, invalid format, and no-op `whatif`.
- Budget breach exit code 2 worked with valid budget keys.
- `caliper export prometheus` gave a clear install hint without `[prom]`.
- `caliper-ai[prom]` served `/metrics` successfully with a normal client.
- TUI numbered navigation did not crash at tested sizes.
- First-run TUI welcome can be dismissed and then reaches Home.
- Default machine-readable redaction held.

## Top Ten Fixes Before Show HN

1. Fix docs-site budget keys immediately.
2. Make empty first-run mention every supported vendor source.
3. Align docs-site install/examples with README and live output.
4. Round percentages in Markdown/table human outputs.
5. Reframe evidence status from fatal "unsupported" to proportional counts.
6. Make TUI `NO_COLOR` actually select an available monochrome/ANSI theme.
7. Add visible TUI navigation for What-If, Budgets, Insights, and Receipt.
8. Reduce default multi-vendor wall-of-tables output.
9. Make `rates catalog` explain embedded vs live-fetched pricing clearly.
10. Tighten 80x24 TUI layout and prevent awkward label wrapping.

## Remediation Status

Implemented in the working tree after this QA pass:

- Docs-site install and budget examples now match the live CLI contract, with
  a docs drift test covering stale budget keys, stale `uvx` guidance, and old
  credits examples.
- Empty first-run overview now names every enabled vendor source.
- Human CSV/Markdown percentage fields are rounded.
- Overall evidence no longer lets missing git attribution poison cost
  confidence, while still reporting git attribution as its own dimension.
- `advise` now explains confidence thresholds when no recommendations match.
- Default multi-vendor table output stays unified; `--by-vendor` opts into
  one-table-per-vendor output.
- TUI demo mode skips the first-run welcome, `NO_COLOR` maps to a registered
  monochrome theme, help/navigation covers all marketed screens, and Doctor
  redacts local paths by default.
- `statusline --compact`, fresh-install `rates catalog` messaging, Prometheus
  disconnect handling, and a fresh-install smoke script were added.
- Remaining backlog coverage was closed: Doctor redaction now shows basename
  plus status, screenshot regression tests cover the specified TUI matrix,
  pricing evidence prints priced/unsupported counts, `rates catalog` JSON
  includes `catalog_source` and `embedded_available`, and launch docs describe
  the exporter family.

Verification completed:

- `uv run pytest tests/test_evidence.py tests/test_insights.py tests/test_statusline.py tests/test_prom_export.py tests/test_cli_helpers.py tests/test_commands.py tests/test_docs_drift.py tests/tui/test_launch_hardening.py`
- `uv run pytest`
- `scripts/release-smoke.sh`
- `CALIPER_SMOKE_PACKAGE=. scripts/live-release-smoke.sh`
