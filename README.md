<div align="center">

# Caliper

### The cost layer for AI-assisted development.

Reads local Codex, Claude Code, Cursor, and Aider logs. Prints what each PR
cost. Offline. No login.

[![CI](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml/badge.svg)](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/caliper-ai.svg)](https://pypi.org/project/caliper-ai/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

```bash
uvx --from caliper-ai caliper
```

</div>

---

## About Caliper

Caliper is a small, local-first Python CLI that turns AI coding session logs
into one usage record and prints what each pull request cost.

It supports four sources today: OpenAI Codex CLI, Claude Code, Cursor, and
Aider. It reads files those tools already write to your disk, joins them into
one frozen event shape, prices them with sourced rate cards, and attributes
the cost to a PR, a commit, or a project.

There is no daemon, no SDK, no account, and no telemetry. The default code
path makes zero network calls. The only network call in the whole codebase is
an opt-in pricing refresh behind a flag.

Caliper is MIT-licensed and built by one developer who wanted to know which
PRs spent the four-figure bill.

## The problem

You ran Codex, Claude Code, Cursor, or Aider this month. A bill arrived. You
cannot point at one pull request and say what it cost.

The vendor dashboards each speak their own dialect, sit behind a login, and
stop at the model boundary. None of them know which commits, which PRs, or
which projects spent the money.

Caliper reads the logs those tools already write to your disk, joins them
into one event shape, and answers the only question that matters in a budget
review: **what did this PR cost.**

## The 30-second proof

On the machine that wrote this README, three commands.

```bash
caliper overview
```

```text
Caliper - Overview
Vendors: claude-code (74,590 events) · openai-codex (20,500 events)

Last 7 days     48,727 credits     $3,383
Last 30 days    52,691 credits    $10,516
Last 90 days    52,691 credits    $10,897

Events: 95,090
Cache savings: $65,871 at 99.3% cache hit
```

```bash
caliper insights
```

```text
High cache reuse: 99.3% of input tokens served from cache,
saving about $63,415. Keep prompts and file context stable
to preserve cache hits.
```

```bash
caliper project --lookback-days 30
```

```text
SlidesDockerTemp    4 models    18,746 credits    $3,009
ace-ai              4 models    15,603 credits    $1,160
caliper             3 models     9,219 credits      $443
```

Real numbers, one machine, one developer, ninety days. No account. No upload.
The first run took eleven seconds on a cold cache. Later runs are under a
second.

## Who this is for

- **Indie developers paying their own AI bill.** You see the credit card
  charge. You want the line items.
- **Engineering managers running AI-heavy teams.** You want a number per PR
  that survives a budget meeting.
- **Anyone under a strict data policy.** Logs stay on disk. The parser is
  open and small enough to read end to end.

## Who this is not for

- Teams that want a hosted dashboard with sign-in. There are products for
  that. Caliper is not one.
- Teams that have not adopted Codex, Claude Code, Cursor, or Aider. There is
  nothing on disk to read.

If you want this to also speak to GitHub Copilot or to a hosted SaaS, open
an issue. The wedge stays local-first.

## What a PR receipt looks like

```bash
caliper pr 42
```

```text
Caliper - PR #42
128 events  432,118 tokens  $4.82   ·   7 commits

  Vendor        Model                 Events  Tokens (in/out)   Cached   API $
  openai-codex  gpt-5.4 standard          74  210,000 / 31,000     61%   $2.10
  claude-code   claude-sonnet-4.6         31   88,000 / 12,000     48%   $1.12
  cursor        composer                  23   72,118 / 19,000     22%   $1.60
```

`caliper pr <N>` resolves the PR commits and filters local events whose
recorded git SHA matches those commits. If the PR cannot be resolved
automatically, pass an explicit range:

```bash
caliper pr --git-range main...feature-branch
```

The same shape is available per commit (`caliper commit <sha>`) and per
project (`caliper project`).

## How it works, in one breath

1. Caliper reads JSONL session logs from `~/.codex/sessions`,
   `~/.claude/projects`, the local Cursor store, and Aider chat history.
2. It joins them into one frozen event shape: vendor, model, service tier,
   project, session, timestamp, token counts, cache counts, pricing source,
   git SHA where present.
3. It groups, prices, and prints. The pricing catalog ships embedded and
   can be refreshed from public sources behind an explicit flag.

There is no daemon, no agent, no SDK. The default code path makes zero
network calls.

## Install

Requires Python 3.11+. Pick one.

```bash
uvx --from caliper-ai caliper             # zero-install, recommended
uv tool install caliper-ai                # persistent install
pipx install caliper-ai
python -m pip install caliper-ai
```

The PyPI distribution is `caliper-ai`. The command and Python package are
both `caliper`.

## First sixty seconds

```bash
caliper                              # rolling 7 / 30 / 90 summary
caliper doctor                       # verifies your local setup
caliper daily --lookback-days 7      # daily rollup
caliper project --lookback-days 30   # which projects cost what
caliper insights                     # cache and tier signals
```

The first run parses everything and writes a sidecar cache. Later runs reuse
it. Pass `--disable-parse-cache` when you want to bypass the cache.

## Interactive workspace

If you prefer to live inside the data, `caliper-ai` ships with an
interactive Textual workspace built into the base install:

```bash
caliper tui                              # against your real logs
caliper tui --demo                       # synthetic fixture, zero disk reads
```

The TUI is a single Python process built on
[Textual](https://github.com/Textualize/textual). It reuses every pure
module the classic CLI uses (parser, pricing, aggregation, windows,
insights) and adds only presentation: a Home overview with cost
cards, primary/secondary limit panels, the insights feed, and recent
sessions. The remaining screens (Sessions, Projects, Models, Limits,
Live, Forecast, What-If, Budgets, Doctor, Receipt) navigate via `1..9`
and fill in over subsequent releases.

Offline by default. No login. No telemetry. The classic CLI surface
keeps working exactly the way it did before — the TUI is an
*additional* entry point, never a redirection.

## Privacy is a constraint, not a feature

- No login, ever.
- No upload, ever.
- No telemetry, ever.
- Prompts and titles are redacted in default output. Pass `--show-prompts`
  if you want them. JSON output never leaks session titles when redaction
  is on. It falls back to session IDs.
- The only network call in the codebase is the opt-in pricing refresh,
  gated by `--allow-network`. The privacy invariant is tested.

If you do not trust the claim, read `src/caliper/parser.py` and
`src/caliper/parse_cache.py`. They are short on purpose.

## Pricing is explicit

- Money is computed in `Decimal`.
- Cached input, cache creation, output, and reasoning tokens are tracked
  separately when the source exposes them.
- Long-context multipliers are applied per model.
- Unknown or partial pricing is surfaced as a warning, never silently
  guessed.
- The embedded rate card carries a `checked` date. `caliper doctor` warns
  past 30 days and fails past 90.

```bash
caliper rates show
caliper rates catalog
caliper rates refresh --allow-network
```

Use a pinned rate card when you need to match an invoice exactly:

```bash
caliper daily --rate-card-file ./rates.json
```

## Budgets in CI

Caliper exits with stable codes so CI can gate on cost.

```toml
# .caliper.toml
[budgets]
daily_credits = 25000
weekly_credits = 100000
monthly_api_dollars = 500
```

```bash
caliper budgets check
```

| Exit | Meaning |
|------|---------|
| `0`  | ok |
| `1`  | warning threshold crossed |
| `2`  | breach threshold crossed |

Add the command to your CI step. The exit code is the contract.

## Exports

```bash
caliper export receipt --receipt-month 2026-05 --receipt-format html
caliper export prometheus --metrics-port 9090
caliper export grafana
```

Receipts render as Markdown or HTML and are suitable for finance handoff.
The Prometheus exporter is a local process. The Grafana exporter prints a
dashboard JSON. The optional `[prom]` extra brings `prometheus-client` in.

## Python library

```python
from caliper.parser import load_usage
from caliper.config import build_options
from caliper.aggregation import aggregate_total

options = build_options(days=7)
result = load_usage(options)
total = aggregate_total(result, options)

print(total.totals.total_tokens)
```

The public import path is `caliper`. The dataclasses are frozen.

## Configuration

```bash
caliper init                        # writes a commented .caliper.toml
```

Environment overrides:

- `CALIPER_CACHE_DIR`: parse-cache location.
- `CALIPER_DATA_DIR`: pricing-catalog location.
- `CODEX_HOME`: Codex CLI data location.
- `CLAUDE_CONFIG_DIR`: Claude Code data location.

## FAQ

**Does it work with Cursor today?**
Yes, for session files. Some Cursor files do not carry per-event token
counts. `caliper doctor` flags those and the event still appears in
session-level rollups.

**Why not just read the vendor dashboards?**
Because the dashboards are per-vendor and per-account. They do not know
which commit, which PR, or which project spent the money. They also
require a login, which is the wrong fit for offline-only workflows.

**How accurate are the costs?**
As accurate as the rate card. The rate card ships embedded with a
`checked` date and warns when it ages. You can pin a local rate card to
match an invoice exactly.

**What about the Anthropic admin API or the OpenAI usage API?**
Out of scope on purpose. Caliper is local-only. The trade-off is named:
you get nothing if the vendor never wrote a log to disk.

**Can I self-host the export?**
Yes. The Prometheus and Grafana exporters are local processes. The
HTML receipt is a file you can email yourself.

**Is there a hosted version?**
No. There is no hosted version on the roadmap. If your team needs a
hosted dashboard, Caliper is the wrong tool. The wedge stays local.

## Development

```bash
uv sync --all-extras --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run pytest --cov=src/caliper --cov-report=term
```

Build and inspect the package:

```bash
rm -rf dist
uv run python -m build
uvx twine check dist/*
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution surface
(rate-card updates, new vendor parsers, schema changes).

## Who built this

I am [Rajdeep Mondal](https://github.com/rajdeepmondaldotcom). I built
Caliper because I had a four-figure AI coding bill, a clear hunch about
which projects caused it, and no offline way to prove it. The first
version paid for itself in one PR review.

If Caliper saves you a meeting, a fight, or a renewal, that is the
intended outcome.

## License

MIT. See [LICENSE](LICENSE).
