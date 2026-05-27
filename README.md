<div align="center">

# Caliper

### The private receipt for your AI coding.

See what your AI coding actually costs, and whether it's working. Caliper reads
the logs **already on your disk** and prices every project, PR, model, and
session at API rates. Fully offline.

**No account. No upload. No telemetry. Nothing leaves your machine.**

[![CI](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml/badge.svg)](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/caliper-ai.svg)](https://pypi.org/project/caliper-ai/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

See the full report right now, on built-in sample data. No install, nothing of yours touched:

```bash
uvx --isolated --from caliper-ai caliper dashboard --demo --open
```

</div>

![Caliper dashboard — verdict, KPIs, and next actions in Safe Share mode](https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/main/docs/screenshots/hero.png)

<p align="center"><sub>Safe Share mode: paths, projects, and session labels are redacted while costs, evidence status, and next actions stay visible.</sub></p>

---

## The honest pitch

On a flat $200/month plan, you're flying blind. Did you pull $4,000 of
API-equivalent coding out of that subscription last month, or $60? You can't
tell. You can't see which project ate the tokens, which PR was expensive, or
whether one runaway session blew the week.

**Caliper won't save you money on a fixed plan. There's nothing to save.** It
does something more useful. It shows where your tokens went and what they were
worth, priced at real API rates and tied to your real work.

If you're on metered API usage, those same numbers are your actual bill, and the
avoidable-spend findings are real money.

Either way, the answer never leaves your machine.

## Why this matters

AI now writes a large and growing share of the code shipped every day, and
almost nobody can measure whether it's helping. You can see your cloud bill,
your error rate, and your test coverage. You can't see what your AI coding
produced: which PRs it shipped, which projects it sped up, and where it spun in
debug loops and burned tokens for nothing.

The numbers that do exist come from the tools selling you the tokens. There's no
independent meter. Caliper is built to be that meter, and it earns the word
"independent" honestly. It runs on the logs already on your disk, answers to no
account, and never phones home, so its numbers have no reason to flatter the
spend.

Today it answers the first half rigorously: what each PR, project, model, and
session cost, and where that spend is avoidable, every figure graded by the
evidence behind it. That is the groundwork for the question every engineer and
every team is now asking out loud: **is this working, and where?**

## What your spend produced

The dashboard opens with a short, honest answer to that question, built from the
git history and tool calls already on your machine:

![What this produced: commits touched, cost per commit, share of spend linked to a commit, and the edit-vs-diagnose ratio](https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/main/docs/screenshots/output.png)

- **Commits touched.** How many distinct commits were checked out while the AI
  was working.
- **Cost per commit.** Git-linked spend divided by commits touched. A unit cost,
  not an invoice.
- **Linked to a commit.** The share of spend recorded at a known commit. The
  rest is exploration, planning, or work that never reached a commit. That is
  not automatically waste, and Caliper says so.
- **Edits vs. diagnose/run.** The share of tool calls that changed files versus
  ran shells and tests. A lot of diagnosing and very little editing is the rough
  shape of a session that spun instead of shipped.

These are signals, not a verdict, and every one is labeled with the assumption
behind it. Caliper measures cost and effort. It does not grade whether the code
was good. You still decide that. But for the first time you can see, privately,
where your AI spend turned into commits and where it just turned into tokens.

## What it answers

AI coding tools are good at spending tokens and bad at explaining the spend.
Vendor dashboards are per-tool, per-account, behind a login, and metered plans
hide the per-token reality behind a flat price. None of them know your local
git history, your PRs, or which project caused the work.

Caliper reads the local trails from Codex CLI, Claude Code, Cursor, and Aider,
prices them with dated, sourced rate cards, and answers questions those
dashboards can't:

- What did this PR cost?
- Which project is driving the spend?
- Where is spend avoidable, and how confident is that?
- Am I getting my money's worth out of a flat subscription?
- Are these numbers exact, estimated, partial, or unsupported?

## The first 30 seconds

```bash
caliper dashboard
```

No logs yet? Run `caliper dashboard --demo` to explore the full report with
built-in sample data before pointing Caliper at your own usage.

It opens a self-contained HTML file in your browser. The verdict sits above the
fold: period, cost, trend, and the top fix it found.

```text
Caliper · Last 30 days · $1,243 · trend +8.2% · top fix: Move low-output
                                  fast tier calls to standard ($96.40)
Avoidable: $176.64 across 3 recommendations. Reproduce with `caliper recommend`.
Theme: dark · local-only · re-render: caliper dashboard --open
```

If Caliper detects a flat-rate subscription, the headline cost is labeled
**API-equivalent value, not a bill** right where you'd read it — so nobody
mistakes "what your usage is worth" for "what you owe."

Every KPI on the page has a **"show the math"** disclosure: the formula, the
rate card date, and the sample size. Evidence, anomalies, avoidable spend, and
session rows show the source quality behind each number instead of forcing you
to trust an unexplained total.

Large first runs may spend a moment indexing local log history; later runs reuse
the local parse cache. Inspect it with `caliper cache status`, clear it with
`caliper cache clear`, or relocate it with `CALIPER_CACHE_DIR`.

### Rate cards stay current — on your terms

Costs are priced from a rate card embedded at release time. See exactly which
card is active and how old it is:

```bash
caliper rates show     # active rate card, its sources, and its age
```

Caliper is offline by default and never fetches on its own. When you want the
latest published pricing, opt in explicitly:

```bash
caliper rates refresh --allow-network
```

This is the auditable backing for every dollar: `rates show` names the dated,
sourced rate card behind the prices, and the dashboard's per-KPI "show the math"
disclosures expand the formula and sample size on top of it.

## Dashboard tour

These screenshots come from `caliper dashboard --safe-share`, so they show the
real report layout without exposing local paths or session identities.

| Next actions | Spend drivers |
|---|---|
| <img alt="Dashboard next actions with verdict, priority actions, and selected-window cost" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/main/docs/screenshots/hero.png"> | <img alt="Spend drivers grouped by vendor, model and tier, service tier, and source" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/main/docs/screenshots/usage-mix.png"> |

| Anomalies | Avoidable spend |
|---|---|
| <img alt="Spend spike anomaly rows with human-readable dates and impact labels" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/main/docs/screenshots/anomalies.png"> | <img alt="Ranked avoidable-spend findings, detected inefficiencies, and cache reuse panels" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/main/docs/screenshots/inefficiencies.png"> |

| Session drilldown | Attribution and evidence |
|---|---|
| <img alt="Session drilldown table with redacted session labels, started time, project, cost, tokens, tools, models, and reason" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/main/docs/screenshots/sessions.png"> | <img alt="Attribution panels for agents, skills, tier sources, long-context boundary, and cohort deltas" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/main/docs/screenshots/attribution.png"> |

## How it's different

| | Caliper | Hosted proxies (Helicone, Langfuse, …) |
|---|---|---|
| Where data lives | Local disk | Their servers |
| Sits on the request path | No | Yes — proxy or SDK |
| Login required | No | Yes |
| Reads existing AI-tool logs | Yes — Codex, Claude Code, Cursor, Aider | No — needs you to route through them |
| Per-PR / per-project cost | Yes — local git attribution | If you instrument it |
| Works with WiFi off | Yes | No |

Caliper is the receipt built from evidence already on your machine. If you need
a request-path proxy, use one of those. If you want to know what last month
actually cost, without sending prompts to a third party, use this.

## What you get

| Surface | Command | Purpose |
|---|---|---|
| Browser dashboard | `caliper dashboard` | Next actions, what your spend produced, spend drivers, avoidable spend, anomalies, sessions, evidence. |
| PR receipt | `caliper pr 42` | Cost of events that recorded the PR's commit SHAs (it states how much of window spend that covers). |
| Overview | `caliper overview` | Rolling 7 / 30 / 90 day spend. |
| Project rollup | `caliper project` | Spend by repository or folder. |
| Model rollup | `caliper models` | Spend by model and vendor. |
| Evidence report | `caliper evidence` | How trustworthy each dimension is. |
| Advisor | `caliper advise --strict` | Ranked, dollar-anchored fixes. |
| Doctor | `caliper doctor` | Local setup + data coverage. |
| Budgets | `caliper budgets check` | CI-friendly warning / breach exits. |
| TUI | `caliper tui` | Interactive terminal workspace. |

### PR receipt

```bash
caliper pr 42
```

```text
Caliper · PR #42
128 events  432,118 tokens  $4.82   ·   7 commits

  Vendor        Model                 Events   Tokens (in/out)    Cached   $
  openai-codex  gpt-5.4 standard          74   210,000 /  31,000    61%   $2.10
  claude-code   claude-sonnet-4.6         31    88,000 /  12,000    48%   $1.12
  cursor        composer                  23    72,118 /  19,000    22%   $1.60
```

Missing git attribution is surfaced as **partial evidence** instead of being
silently treated as exact.

## What the dollar figures mean

Caliper is precise about what its numbers are, because the framing changes with
how you pay:

- **Metered API usage** (API keys, usage-based billing). The cost total is your
  actual bill, and avoidable-spend findings are real money you would stop
  spending.
- **Flat-rate subscription** (a fixed monthly plan). The cost total is the
  **API-equivalent value** of your usage — what the same work would cost on the
  meter. It is not an invoice, and a flat plan has nothing to refund. Avoidable
  spend here means wasted tokens, slower loops, and rate-limit pressure, not
  cash back. Caliper labels this everywhere it shows the number.

Pricing math is identical in both modes. Only the label changes, and Caliper
never pretends a flat-plan total is a bill.

## Trust model

| Boundary | Default |
|---|---|
| Login | none |
| Upload | none |
| Telemetry | none |
| Daemon | none |
| Request proxy | none |
| Network calls during usage analysis | none |
| Pricing refresh | explicit `--allow-network` |
| GitHub PR lookup | explicit `--allow-network` |
| Prompt output | redacted |
| Absolute paths | redacted in machine-readable output |
| Parse cache | local SQLite only; may contain local paths/session metadata |

The privacy invariant is enforced in CI. The generated HTML contains zero
external resources, zero `<script src>`, zero `fetch`/`XMLHttpRequest`/`import()`.
Interactive dashboards use one inline UI script and one JSON data block; pass
`--no-interactive` for script-free HTML.

The parse cache is not telemetry and is never uploaded. It stores parsed usage
events, source file fingerprints, and enough local metadata to avoid reparsing
unchanged logs. Disable it per run with `--no-parse-cache`.
You can verify it on the file Caliper wrote (default location shown):

```bash
grep -E "://|<link|<script src|fetch\(|XMLHttpRequest|import\(" ~/Downloads/caliper-dashboard-*.html
# no matches
```

## Accuracy

Caliper does not pretend every local log is perfect. It reports what the
evidence supports.

- Costs use `Decimal`.
- Cached input, cache creation, output, and reasoning tokens are tracked
  separately when vendors expose them.
- Long-context multipliers are applied per model.
- Codex Fast mode is priced with sourced model-family multipliers and kept
  separate from standard-tier usage in dashboard spend drivers.
- Unknown pricing is surfaced as a warning, not silently guessed.
- Anomaly detection uses robust σ (MAD × 1.4826, IQR / 1.349) with a $1
  absolute floor — no more "354,210σ" on a sparse Tuesday.
- Evidence is graded `exact`, `estimated`, `partial`, or `unsupported`. Each
  KPI exposes its formula inline.

```bash
caliper evidence
caliper doctor
caliper rates show
```

## Budgets in CI

```toml
# .caliper.toml
[budgets]
daily_cost_usd = 25
weekly_cost_usd = 100
monthly_cost_usd = 500
```

```bash
caliper budgets check
```

| Exit | Meaning |
|---:|---|
| `0` | ok |
| `1` | warning threshold crossed |
| `2` | breach threshold crossed |

## Supported sources

| Source | What Caliper reads |
|---|---|
| OpenAI Codex CLI | Local session logs, state DB, model + token fields. |
| Claude Code | Project JSONL logs, tool-use, cache token fields. |
| Cursor | Local token-bearing records where available. |
| Aider | Local chat history + usage records. |

Files that are transcript-only or missing token counts are surfaced by
`caliper doctor` so coverage stays explicit.

## Install

Requires Python 3.11+.

```bash
# Recommended.
uv tool install caliper-ai
uv tool upgrade caliper-ai
```

The PyPI package is `caliper-ai`; the command is `caliper`.

<details>
<summary>Other install paths (pipx, venv + pip, uvx)</summary>

```bash
# pipx
pipx install caliper-ai
pipx upgrade caliper-ai

# venv + pip
python -m venv .venv && source .venv/bin/activate
python -m pip install caliper-ai

# uvx one-off (use --from to avoid name-collision resolution)
uvx --isolated --from caliper-ai caliper dashboard --demo --open
```

If `uv` can't see a just-published version (stale PyPI index or resolver
cache):

```bash
UV_NO_CACHE=1 uv tool install --force caliper-ai
```

</details>

## FAQ

**Will Caliper save me money?** Not on a flat plan. There's nothing to save.
It gives you visibility: what your usage is worth at API rates, where it goes,
and where it's avoidable. On metered API usage, the avoidable-spend findings
are real money.

**What does the cost number mean on a subscription?** It's the API-equivalent
value of your usage, not a bill. Caliper labels it that way everywhere it shows
the number. Run `caliper evidence` for the full breakdown.

**Does it measure whether AI is actually making me productive?** It measures the
honest, local half of that: cost per commit, how much spend linked to a commit
at all, and the ratio of editing to diagnosing. It does not judge whether the
code was good, and it never claims a commit equals value. Those are signals to
read, not a score to trust blindly.

**Does it work with Cursor today?** Yes, when Cursor's local data includes
token-bearing records. Some Cursor files are transcript-only. `caliper doctor`
reports which.

**How accurate are the costs?** As accurate as your local logs and rate card
allow. Run `caliper evidence` to see which dimensions are exact, estimated,
partial, or unsupported.

**Does Caliper upload prompts?** No. Default usage analysis is local-only and
redacts prompt-like fields from normal output. CI tests the privacy invariant
on every commit.

**Is there a hosted version?** No. There is no hosted version on the roadmap.
Caliper is intentionally a tool you run, not a service you log into.

## See it for yourself

One command, on built-in sample data. No install, nothing of yours touched:

```bash
uvx --isolated --from caliper-ai caliper dashboard --demo --open
```

Then point it at your own logs:

```bash
uv tool install caliper-ai
caliper dashboard
```

## Development

```bash
uv sync --all-extras --dev
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for rate-card updates, new vendor
parsers, schema changes, and release hygiene.

## Who built this

[Rajdeep Mondal](https://github.com/rajdeepmondaldotcom). I had a four-figure
AI coding bill, a strong hunch about which work caused it, and no offline way
to prove it. Then I moved heavy work onto a flat plan and realized I now had
the opposite problem: no idea what I was actually getting. Caliper answers both
questions from the logs already on your disk, without sending anything anywhere.

## License

MIT. See [LICENSE](LICENSE).
