# Caliper 0.0.22 Final Live Release QA - Brutal Feedback

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.22`
Git target checked: `26feda4`, tag `v0.0.22`

## Verdict

Caliper 0.0.22 is in good enough shape for a serious beta / Show HN launch if
the launch copy is fixed first. It is not "perfect UI/UX."

The live package is real. Fresh installs work, the parser surface works across
Codex, Claude Code, Cursor, and Aider-shaped data, JSON privacy redaction held,
bad-input handling is sane, the TUI fixes from 0.0.21 mostly landed, and the
full local suite is green.

The remaining problem is public trust and terminal polish. If the launch uses
the current `docs/launch/*` drafts, HN will catch stale install commands and
the old "credits" story immediately. If a terminal-native user runs project
reports in an 80-column pane, the table wraps words like `Anthro\npic` and
`gpt-5.\n5`, which makes the product feel less mature than the underlying
parser. If a privacy skeptic screenshots the default table output, the
absolute session root is visible even though machine-readable output redacts
paths correctly.

Short answer: the library is useful and shippable as a beta. It is not yet
polished enough to claim "perfect." Do not post the current launch drafts
without edits.

## Evidence Gathered

- Verified PyPI latest through `https://pypi.org/pypi/caliper-ai/json`:
  `info.version == 0.0.22`, release URL `.../caliper-ai/0.0.22/`.
- Verified local release identity: `pyproject.toml` version `0.0.22`,
  `git tag v0.0.22`, `HEAD == 26feda4`.
- Install channels:
  - `uvx --isolated --refresh --from caliper-ai==0.0.22 caliper --version`
    returned `0.0.22 (rates checked 2026-05-13)`.
  - `pipx run --spec caliper-ai==0.0.22 caliper --version` returned the same.
  - Fresh `python3 -m venv` + `pip install caliper-ai==0.0.22` returned the
    same.
- Repo verification:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed.
  - `uv run pytest` passed: `533 passed`.
  - `CALIPER_SMOKE_VERSION=0.0.22 scripts/live-release-smoke.sh` passed.
  - `scripts/release-smoke.sh` passed, including Prometheus, receipts, schema,
    compare, what-if, budgets, commit, and PR-range smoke checks.
- Hostile fixture:
  - Built a clean temp venv with `caliper-ai[prom]==0.0.22`.
  - Created Codex, Claude Code, Cursor, and Aider-shaped local data.
  - Verified `vendors list --format json` detected all four vendors.
  - Verified `overview --format json` did not contain `/tmp/sample-workspace`,
    the QA temp root, private prompt text, or private session title.
  - Verified `--show-paths` restored the expected absolute paths.
  - Verified malformed TOML exits 2 with a one-line `error:` message and no
    Python traceback.
  - Verified `budgets check` exits 2 for weekly/monthly breaches.
  - Verified `--since "last 7 days"` works on `daily`.
  - Verified TUI run-test reaches `ReceiptScreen`, `WhatIfScreen`,
    `BudgetsScreen`, `InsightsScreen`, `DoctorScreen`, and `HelpScreen`.
  - Verified `NO_COLOR=1` selects the `monochrome` TUI theme.

## Launch-Killer Findings

### P0 - Do not publish the current launch drafts

Personas: HN drive-by installer, YC partner, launch-day pedant.

`README.md` and PyPI now correctly lead with:

```bash
uvx --isolated --from caliper-ai caliper
```

But launch drafts still say:

```bash
uvx --from caliper-ai caliper
```

Found in:

- `docs/launch/hn-show.md`
- `docs/launch/linkedin-launch.md`
- `docs/launch/tweet-launch.md`
- `docs/launch/README.md`

The Show HN draft also still shows:

```text
Last 7 days      1,234 credits        $42
Last 30 days     1,980 credits       $187
Last 90 days     2,100 credits       $219
```

The live product and README have moved to token/cost/evidence language. If
the launch post says "credits," HN will reasonably ask whether the numbers
are old, whether the current release was tested, and whether the author is
posting stale marketing copy.

Brutal feedback: this is the easiest way to lose launch trust without a code
bug. The package can be right and the thread can still become "the launch copy
is stale."

## Product / UX Findings

### P1 - 80-column human tables still look bad

Personas: terminal power user, HN CLI reviewer, Reddit first-run user.

At `--width 80`, `caliper project` wraps critical labels into fragments:

```text
│        │ gpt-5. │
│        │ 5      │
...
│        │ Anthro │
│        │ pic    │
...
│        │ unknow │
│        │ n      │
```

The session root also wraps across lines before the table:

```text
Session root:
/var/folders/.../caliper-022-hostile-qa-...
/codex/sessions
```

`--compact` improves numeric width but does not fix the label wrapping. A
terminal-native product gets judged in split panes and 80-column windows. This
output says "engineer debug report," not "polished CLI."

Brutal feedback: HN users will forgive a plain table. They will not forgive a
table that saws model names and provider names in half.

### P1 - Human output exposes absolute local source paths by default

Personas: privacy skeptic, security reviewer, screenshot-driven HN critic.

Machine-readable output redacts paths correctly. Default human table output
still prints the absolute session root. On a real laptop that will often reveal
the local username and directory structure.

This is not a data exfiltration bug. It is a privacy perception bug. The
product's pitch is "offline, no upload, redacted by default." A screenshot with
`<home-dir>/...` weakens that story even if the implementation is otherwise
safe.

Brutal feedback: if privacy is the wedge, every default screenshot must look
privacy-aware.

### P1 - Unknown pricing can look like a real $0 row

Personas: finance user, engineering manager, skeptical founder.

In the hostile mixed-vendor fixture, overview warned:

```text
2 events used models with no known rate card.
```

Evidence correctly said:

```text
pricing partial: 3 priced, 1 unsupported
```

But project table rows can still show an unknown-priced Cursor model as `$0`
instead of making unsupported pricing visually unavoidable. A budget reviewer
can read that as "Cursor was free" instead of "Caliper could not price this
model from the local rate card."

Brutal feedback: cost tools cannot let "unknown" look like "zero." That is a
trust leak.

### P2 - Markdown exports are syntactically clean but finance-unfriendly

Personas: finance handoff user, HN copy-paster.

`compare --format markdown` emitted values like:

```text
| cost_usd | 0.3206750 | 0 | 0.3206750 | 0.00 |
```

`whatif --format markdown` emitted:

```text
| cost_usd | 0.3206750 | 0.2706750 | -0.0500000 | -15.59 | vendor-reported |
```

This no longer has ugly Python float repr noise, which is good. But it still
looks like raw internals: no `$`, no percent sign, too many decimal places for
human-facing money.

Brutal feedback: if the README says receipts are suitable for finance, the
Markdown paths should look like they were designed for humans, not just parsed
by tests.

### P2 - `rates catalog` floods the terminal

Personas: CLI power user, HN "Unix philosophy" commenter.

`caliper rates catalog` prints a huge table. JSON output in the test contained
1,968 models. The table starts with generic providers and truncates model names
heavily.

The command works, but it needs a better first-run shape: summary by provider,
filter/search flags, `--top`, or a prompt to use JSON. Today it is technically
correct and practically overwhelming.

Brutal feedback: "I ran the command from the docs and got a wall of truncated
model names" is not a premium CLI moment.

### P2 - The `overview` command is less scopeable than the rest of the CLI

Personas: shell user, QA-minded HN commenter.

Many report commands accept `--days` / `--lookback-days` and `--since`.
`overview` is fixed to rolling 7/30/90 and rejects both `--days` and
`--lookback-days`.

That is defensible if intentional, but the CLI mental model is inconsistent.
I hit this while writing the hostile harness. A real user will hit it while
trying to reproduce a smaller window.

Brutal feedback: either make `overview` explicitly fixed-window in help text
or accept a scoping flag and still show the 7/30/90 rollup relative to it.

## Persona Reactions

### YC Technical Partner

"The wedge is good: local logs to PR cost is specific, and the offline
constraint is crisp. The app is good enough to show. But if your launch
post has stale commands, I immediately wonder whether the rate card is stale
too. Fix the trust surface before asking for attention."

### Hacker News CLI Skeptic

"The install works, the no-login claim is credible, and the source is small
enough to inspect. But the tables still wrap like a weekend script. Also, do
not show me old 'credits' copy in the Show HN draft while the README says
something else."

### Reddit First-Time User

"The empty state is much better now. It says all the tools it checked. Demo
mode works. But if my first useful report looks like a broken spreadsheet in
my terminal, I am not going to read the docs to discover `--format json`."

### LinkedIn Engineering Manager

"Budgets and receipts are the business value. I like the exit codes. But I
need unsupported pricing to be impossible to mistake for zero. If I take this
to a budget meeting, the tool must be more conservative than the person using
it."

### Privacy Reviewer

"The JSON redaction passed. The prompt and title did not leak. Good. But your
human output still prints absolute local roots. If privacy is a constraint,
make the default screenshots boring."

### Terminal Power User

"The TUI is no longer the obvious weak point. Shortcut navigation and
NO_COLOR work. The classic CLI table rendering is now the bigger visual
problem."

## What Passed And Should Be Protected

- Published package identity is consistent: PyPI, local tag, package metadata,
  and runtime `--version` all say `0.0.22`.
- Fresh install paths worked via `uvx`, `pipx run`, and venv `pip`.
- Full local suite passed: `533 passed`.
- Live release smoke passed against the published wheel.
- Multi-vendor parsing worked in a fresh temp venv.
- Empty first-run overview now names Aider, Claude Code, Cursor, and OpenAI
  Codex.
- JSON redaction held for absolute paths, temp roots, prompts, and private
  titles.
- `--show-paths` correctly makes paths visible.
- Bad config handling is clean: exit 2, one-line `error:`, no traceback.
- Natural-language `--since "last 7 days"` works.
- TUI demo skips the prior first-run gate, reaches secondary screens, and
  honors `NO_COLOR=1`.
- Prometheus smoke passed.

## Final Answer

Is it in good enough shape?

Yes, if the target is a serious beta / Show HN launch and the stale launch
drafts are fixed first. No, if the bar is "perfect UI/UX." The product core is
credible. The remaining work is mostly about trust surfaces: launch copy,
human table rendering, path display, and making unsupported pricing impossible
to misread.
