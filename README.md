<div align="center">

# Caliper

### The local cost ledger for AI-assisted development.

Run one command. Get a private HTML dashboard showing what your AI coding
actually cost — by project, PR, model, vendor, and session.

**Offline by default. No account. No upload. No telemetry.**

[![CI](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml/badge.svg)](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/caliper-ai.svg)](https://pypi.org/project/caliper-ai/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

```bash
uv tool install caliper-ai
caliper dashboard
```

</div>

![Caliper dashboard — verdict, KPIs, and next actions in Safe Share mode](https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/v0.0.54/docs/screenshots/hero.png)

<p align="center"><sub>Safe Share mode screenshot: paths, projects, and session labels are redacted while costs, evidence status, and recommendations stay visible.</sub></p>

---

## Why it exists

AI coding tools are good at spending tokens and bad at explaining the bill.
Vendor dashboards are per-tool, per-account, and behind logins. They don't
know your local git history, your PRs, or which project caused the spend.

Caliper reads the logs **already on your disk** from Codex CLI, Claude Code,
Cursor, and Aider, prices them with sourced rate cards, and answers questions
those dashboards can't:

- What did this PR cost?
- Which project is driving the bill?
- How much did cache reuse save?
- Are these numbers exact, estimated, partial, or unsupported?

The answer never leaves your machine.

## The first 30 seconds

```bash
caliper dashboard
```

No logs yet? Run `caliper dashboard --demo` to explore the full report with
built-in sample data before pointing Caliper at your own usage.

Opens a self-contained HTML file in your browser. The verdict sits above the
fold — period, cost, trend, and the top fix Caliper found:

```text
Caliper · Last 14 days · $1,243 · trend +8.2% · top fix: Move low-output fast
                                                tier calls to standard ($96.40)
Fixable: $184.20 across 3 recommendations. Inspect with `caliper advise --strict`.
Theme: dark · local-only · re-render: caliper dashboard --open
```

Every KPI on the page has a **"show the math"** disclosure — the formula, the
rate card date, and the sample size. Evidence, anomalies, savings, and session
rows show the source quality behind the number instead of forcing you to trust
an unexplained total.

Large first runs may spend a moment indexing local log history; later runs reuse
the local parse cache.

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

These screenshots are generated from `caliper dashboard --safe-share`, so they
show the real report layout without exposing local paths or session identities.

| Next actions | Spend drivers |
|---|---|
| <img alt="Dashboard next actions with verdict, priority actions, and selected-window cost" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/v0.0.54/docs/screenshots/hero.png"> | <img alt="Spend drivers grouped by vendor, model and tier, service tier, and source" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/v0.0.54/docs/screenshots/usage-mix.png"> |

| Anomalies | Savings opportunities |
|---|---|
| <img alt="Spend spike anomaly rows with human-readable dates and impact labels" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/v0.0.54/docs/screenshots/anomalies.png"> | <img alt="Recommended savings, detected waste, and cache leverage panels" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/v0.0.54/docs/screenshots/inefficiencies.png"> |

| Session drilldown | Attribution and evidence |
|---|---|
| <img alt="Session drilldown table with redacted session labels, started time, project, cost, tokens, tools, models, and reason" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/v0.0.54/docs/screenshots/sessions.png"> | <img alt="Attribution panels for agents, skills, tier sources, long-context boundary, and cohort deltas" src="https://raw.githubusercontent.com/rajdeepmondaldotcom/caliper/v0.0.54/docs/screenshots/attribution.png"> |

## How it's different

| | Caliper | Hosted proxies (Helicone, Langfuse, …) |
|---|---|---|
| Where data lives | Local disk | Their servers |
| Sits on the request path | No | Yes — proxy or SDK |
| Login required | No | Yes |
| Reads existing AI-tool logs | Yes — Codex, Claude Code, Cursor, Aider | No — needs you to route through them |
| Per-PR / per-project cost | Yes — local git attribution | If you instrument it |
| Works with WiFi off | Yes | No |

Caliper is the receipt from evidence already on your machine. If you need a
request-path proxy, use one of those. If you want to know what last month
actually cost — without sending prompts to a third party — use this.

## What you get

| Surface | Command | Purpose |
|---|---|---|
| Browser dashboard | `caliper dashboard` | Next actions, spend drivers, savings, anomalies, sessions, evidence. |
| PR receipt | `caliper pr 42` | Cost attributed to one pull request. |
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

The privacy invariant is enforced in CI. The generated HTML contains zero
external resources, zero `<script src>`, zero `fetch`/`XMLHttpRequest`/`import()`.
You can verify it on your own file:

```bash
grep -E "://|<script src|fetch\(|XMLHttpRequest|import\(" ~/caliper.html
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
uvx --isolated --from caliper-ai caliper dashboard
```

If `uv` can't see a just-published version (stale PyPI index or resolver
cache):

```bash
UV_NO_CACHE=1 uv tool install --force caliper-ai
```

</details>

## FAQ

**Does it work with Cursor today?** Yes, when Cursor's local data includes
token-bearing records. Some Cursor files are transcript-only. `caliper doctor`
reports which.

**How accurate are the costs?** As accurate as your local logs and rate card
allow. Run `caliper evidence` to see which dimensions are exact, estimated,
partial, or unsupported.

**Does Caliper upload prompts?** No. Default usage analysis is local-only and
redacts prompt-like fields from normal output. CI tests the privacy
invariant on every commit.

**Is there a hosted version?** No. There is no hosted version on the roadmap.
Caliper is intentionally a tool you run, not a service you log into.

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
to prove it. The first version paid for itself in one PR review.

## License

MIT. See [LICENSE](LICENSE).
