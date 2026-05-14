# Caliper 0.0.23 Final Live Release QA - Brutal Feedback

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.23`
Git target checked: `cd4c0f2`, tag `v0.0.23`
PyPI target checked: `https://pypi.org/pypi/caliper-ai/json`, `info.version == 0.0.23`

## Verdict

Caliper 0.0.23 is good enough for a serious public beta / Show HN launch.
It is not "perfect UI/UX."

The release identity is clean, the public package is live, install paths work,
the test suite is green, the smoke scripts pass, docs and launch copy no longer
have the obvious 0.0.22 launch blockers, and the CLI has materially better
first-run, narrow-table, unsupported-pricing, and Markdown formatting behavior.

No P0 launch blocker was found.

The product still has trust and polish gaps that hostile public users will
notice. The sharpest remaining issues are not parser correctness. They are
default JSON exposing repo/session identifiers, 80-column cost cells truncating
the dollar amount, mixed pricing evidence being summarized too loosely, compare
percentages lying when the baseline is zero, and TUI shortcuts/theme behavior
not fully matching the README-level promise.

Brutal version: the core wedge is real. The package will not get killed for
being fake. It can still get dinged for feeling "almost polished" in the exact
places where a cost/privacy tool must feel boringly precise.

## Evidence Gathered

- Verified PyPI latest: `caliper-ai==0.0.23`.
- Verified local release identity:
  - `pyproject.toml` version: `0.0.23`
  - `python -m caliper --version`: `0.0.23 (rates checked 2026-05-13)`
  - `HEAD`: `cd4c0f2 release: prepare caliper 0.0.23`
  - `v0.0.23` resolves to `cd4c0f2`
- Install and packaging checks:
  - `uvx --isolated --refresh --from caliper-ai==0.0.23 caliper --version` passed.
  - `pipx run --spec caliper-ai==0.0.23 caliper --version` passed.
  - Local wheel install into a clean venv passed.
  - Built wheel and sdist from source.
  - `uvx twine check /tmp/caliper-023-build.dYiNlQ/*` passed for both artifacts.
- Repo gates:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: `151 files already formatted`.
  - `uv run pytest` passed: `543 passed in 35.08s`.
  - `CALIPER_SMOKE_VERSION=0.0.23 scripts/live-release-smoke.sh` passed.
  - `scripts/release-smoke.sh` passed.
- Hostile fixtures:
  - Built multi-vendor Codex, Claude Code, Cursor, and Aider fixture with private
    path, prompt, title, repo slug, unknown model pricing, transcript-only Cursor
    file, rate-limit samples, bad TOML, bad JSON rates, bad tier map, and budget
    breach data.
  - Verified default JSON did not leak `SECRET_PROMPT`, `Project Nightfall`, or
    `/Users/alice`.
  - Verified default human output redacts the session root as `<redacted-path>`.
  - Verified `--show-paths` restores absolute paths intentionally.
  - Verified empty first-run overview now gives useful next steps.
  - Verified TUI navigation reaches Home, Intervals, Sessions, Projects, Models,
    Limits, Live, Forecast, Doctor, Receipt, What-If, Budgets, Insights, and Help
    in 80x24 and 120x40 test pilots.
  - Verified `NO_COLOR=1` initially selects the monochrome TUI theme.

## P0 Findings

None found.

That matters. The previous class of launch-killers was stale install copy,
stale credits language, broken first-run states, path leakage in obvious places,
and weak unsupported-pricing display. 0.0.23 clears those at the main launch
surface.

## P1 Findings

### P1 - Default JSON still exposes repo and session identifiers

Personas: privacy skeptic, security reviewer, HN commenter who searches JSON
before reading the README.

Default JSON redacts absolute paths and prompt/title content. Good.

But the hostile fixture still exposed:

```text
2026-05-15T04-00-00-private-acquisition
git@github.com:stealth/private-acquisition.git
```

Those are not absolute local paths, but they are still private identifiers. If
a user shares JSON in a GitHub issue, Slack thread, support request, or finance
handoff, repo names and session stems can reveal exactly the thing they thought
"redacted by default" protected.

Brutal feedback: a privacy-first cost tool cannot make users learn the hard way
that "redacted" means "paths and prompts, but not repo identities." Either
redact repo/session identifiers by default, add a `--show-repos` style reveal
flag, or say the current boundary plainly in docs and JSON schema notes.

### P1 - 80-column project tables still hide the money

Personas: terminal power user, HN CLI reviewer, engineering manager sharing a
terminal screenshot.

The 0.0.23 narrow tables no longer split `Anthropic` into fragments or saw model
names in half. That is a real improvement.

But `caliper project --width 80` still truncates the most important cell:

```text
│ secret-acquisition-di… │ gpt-5.5 · sonnet-4.6… │ 206,… │ $0… │ partial       │
│ private-repo           │ aider-reported        │ 3,250 │ $0… │ vendor-repor… │
```

Brutal feedback: this is a cost tool. The dollar cell must never become `$0...`.
Drop the model column, shorten the group harder, or switch to a stacked layout.
Do not hide the number users came for.

### P1 - Mixed pricing status is still too easy to misread

Personas: finance operator, skeptical founder, budget reviewer.

The models table correctly renders the unknown Cursor model as `n/a`:

```text
cursor-mystery-unknown-... | n/a | partial
```

That is the right direction. But aggregate rows in the same hostile run still
summarized mixed exact/vendor/unsupported data as `vendor-reported` in places
where the evidence table says the overall state is `partial`.

Brutal feedback: "vendor-reported" sounds trustworthy. In a mixed aggregate
with one unsupported model, the total should say `partial` or `mixed`, not the
friendliest sub-status. Finance users will not cross-check another command
before pasting the table.

### P1 - Compare Markdown lies when the baseline is zero

Personas: finance user, HN pedant, dashboard builder.

The Markdown formatting itself is now much better:

```text
| cost_usd | $2.50 | $0.00 | +$2.50 | 0.00% |
| tokens | 250,000 | 0 | +250,000 | 0.00% |
```

The percentage is wrong as a user-facing statement. Going from zero to nonzero
is not `0.00%`. It is `n/a`, `new`, `inf`, or "no baseline."

Brutal feedback: HN will absolutely catch this. A cost tool cannot get the
semantic edge case wrong in a copy-pasteable Markdown report.

## P2 Findings

### P2 - Root option placement remains inconsistent

Personas: Reddit power user, CLI skeptic, person writing CI commands by hand.

This works:

```bash
caliper --width 100 advise ...
```

This fails:

```bash
caliper advise ... --width 100
```

The error is:

```text
No such option: --width
```

Several commands duplicate common flags after the subcommand, so users learn
that style. Then `advise`, `whatif`, `budgets check`, and `compare` reject some
reasonable flags or require different names.

Brutal feedback: this is the sort of Typer/Click papercut that makes a polished
CLI feel internally inconsistent. It is not a launch blocker, but it will
produce annoying comments and bad copy-paste snippets.

### P2 - Budget JSON exposes raw float precision

Personas: finance operator, dashboard builder.

`budgets check --format json` correctly exits `2` on breaches and now includes
window metadata. Good.

But one field still looks raw:

```json
"used_percent": 8333.333333333334
```

Brutal feedback: JSON can be machine-oriented, but ugly precision in a finance
payload tells users the formatting pass was not complete. Add exact/string
fields or quantize percentages.

### P2 - Rates catalog is usable now, but still looks raw

Personas: CLI power user, HN "Unix philosophy" commenter.

0.0.23 caps the default table and prints a useful hint:

```text
Showing 25 of 1,968 models; use --model, --provider, --limit, or --all.
```

That fixes the wall-of-models problem.

The table still shows values like `3.000000`, `0.5000000`, and `15.000000`.
That is correct but not pleasant.

Brutal feedback: the command no longer floods the terminal, but it still reads
like a raw catalog dump instead of a deliberately designed CLI table.

### P2 - TUI shortcuts are not obviously global

Personas: terminal app user, keyboard-first reviewer.

The TUI navigation pilot passed when each secondary screen returned to Home
before the next shortcut. It reached every shipped screen.

In an earlier rapid-navigation pass, pressing `b` and `i` while already on
What-If stayed on `WhatIfScreen` instead of jumping to Budgets or Insights.
The README says `b` opens Budgets and `i` opens Insights. A user will read that
as global.

Brutal feedback: either make shortcuts global across screens or phrase the help
so users know `Escape` returns Home before the next jump.

### P2 - `NO_COLOR` can be escaped by cycling the theme

Personas: accessibility user, terminal purist, CI screenshot reviewer.

`NO_COLOR=1` initially selected the monochrome theme. Good.

But pressing `t` cycled the app to `parchment`:

```text
mono80: home theme monochrome
theme cycle: slate->parchment, app theme parchment
```

Brutal feedback: if `NO_COLOR` is a contract, the theme cycle should either be
disabled, cycle only monochrome-safe variants, or tell the user that manual
theme selection overrides the environment.

### P2 - TUI rate-limit panels are visually present but not self-explanatory

Personas: live-ops user, manager checking burn rate.

The late TUI Home screenshot showed primary and weekly limit bars after refresh,
but the panels did not show the exact 75 percent / 80 percent sample values from
the fixture. Reset and burn fields were rendered as dashes.

Brutal feedback: bars without exact percentages are okay for ambience, not for a
cost-control tool. If the CLI statusline can print `5h 75%` and `W 80%`, the
Home TUI should expose the same numbers.

## What Got Much Better Since 0.0.22

- Launch copy now uses `uvx --isolated --from caliper-ai caliper`.
- The public PyPI package is actually `0.0.23`; no release drift found.
- Empty first-run overview is useful:

```text
No AI coding usage logs found in the active window.
Checked:
- Aider: no files found
- Claude Code: no files found
- Cursor: no files found
- OpenAI Codex: no files found
Next:
- Run `caliper doctor` to inspect local setup.
- Run `caliper tui --demo` to explore Caliper with sample data.
```

- Default human output redacts the session root as `<redacted-path>`.
- `--show-paths` restores full paths intentionally.
- Unknown pricing shows `n/a` in model/session tables instead of pretending to
  be zero.
- `rates catalog` is capped and filterable.
- Markdown compare and what-if reports use `$`, commas, and `%`.
- TUI demo and real-data navigation reach every real screen.
- `NO_COLOR` initial theme behavior works.

## Persona Feedback

### Hacker News CLI Skeptic

"This is real. The parser works, the install works, and the README is no longer
obviously stale. But I will still post screenshots of `$0...` in the project
table and the compare percentage going from `$0.00` to `$2.50` as `0.00%`.
That is low-hanging credibility damage."

### YC Partner

"The wedge is clear: local logs to PR/project cost. I understand who starts
using it. What I would push on is whether the artifact is defensible in a budget
meeting. Mixed pricing and hidden dollar cells make the receipt less
boardroom-safe than the pitch wants it to be."

### Reddit Power User

"I am going to try every flag order. Some commands accept common flags after the
subcommand, some reject them, and some use different window semantics. I can
figure it out, but I will complain that the CLI feels like several commands
grew independently."

### LinkedIn Engineering Manager

"The screenshots are close enough to share internally, but I need the money to
be visible in narrow terminals. If the report says `$0...`, I cannot paste it
into a budget thread without explaining the tool."

### Privacy/Security Reviewer

"No upload and prompt/path redaction are good. Default JSON still carrying
`git@github.com:stealth/private-acquisition.git` is the gap. Either redact repo
identity by default or document it as intentionally in scope."

### Finance Operator

"I like exact strings for money. I do not like `8333.333333333334` percentages
or baseline-zero deltas. Those need explicit semantics."

### Open Source Maintainer

"The release process looks much healthier now: tests, smoke, wheel/sdist, twine
check, PyPI, changelog. The remaining work is not 'does it run?' It is
consistency and precision."

## Final Answer

Yes, 0.0.23 is in good enough shape for a serious Show HN / public beta.

No, it is not perfect UI/UX.

If the goal is "do not embarrass yourself on launch day," 0.0.23 clears that
bar. If the goal is "top of HN with minimal nitpicks," fix the P1 items first:
JSON repo/session identifier redaction, 80-column dollar visibility, mixed
pricing labels, and zero-baseline compare percentages.
