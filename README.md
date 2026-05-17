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
uvx --isolated --from caliper-ai caliper
```

</div>

---

## About Caliper

Caliper is a small, local-first Python CLI that turns AI coding session logs
into one usage record and prints what each pull request cost.

It supports token-bearing logs from OpenAI Codex CLI, Claude Code, Cursor,
and Aider. It reads files those tools already write to your disk, joins them
into one frozen event shape, prices them with sourced rate cards, and
attributes the cost to a PR, a commit, or a project when the local evidence
contains enough git context.

There is no daemon, no SDK, no account, and no telemetry. The default usage
path makes zero network calls. Optional pricing refresh and GitHub CLI PR
resolution sit behind explicit flags.

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

Four commands against a sanitized local fixture.

```bash
caliper overview
```

```text
Caliper - Overview
Vendors: claude-code (1,240 events) · openai-codex (860 events)

Last 7 days          $42
Last 30 days        $187
Last 90 days        $219

Events: 2,100
Cache savings: $640 at 72.4% cache hit
```

```bash
caliper insights
```

```text
High cache reuse: 72.4% of input tokens served from cache,
saving about $612. Keep prompts and file context stable
to preserve cache hits.
```

```bash
caliper project --lookback-days 30
```

```text
demo-api          4 models     $81
frontend-lab      4 models     $63
caliper-demo      3 models     $43
```

```bash
caliper dashboard --demo
```

The dashboard command writes one self-contained HTML file and opens it in a
browser. `--demo` uses built-in synthetic data, so reviewers can try the
dashboard without reading local logs.

Names and numbers above are sanitized examples. No account. No upload.
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

`caliper pr <N>` uses local fetched pull refs by default and filters local
events whose recorded git SHA matches those commits. Pass `--allow-network`
to let Caliper ask GitHub CLI to resolve the PR commits, or pass an explicit
range:

```bash
caliper pr --git-range main...feature-branch
```

The receipt carries evidence grades, so missing local git attribution is
visible instead of being silently treated as exact. The same shape is
available per commit (`caliper commit <sha>`) and per project
(`caliper project`).

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

Requires Python 3.11+. Pick the line that fits your setup.

```bash
# Zero-install. Ignores any persistent uv tool install. Recommended.
uvx --isolated --from caliper-ai caliper

# Persistent global tool (uv). Good for daily use.
uv tool install caliper-ai
uv tool upgrade caliper-ai     # later, to update

# Persistent global tool (pipx). Works the same way.
pipx install caliper-ai
pipx upgrade caliper-ai

# Plain pip inside a virtualenv. Standard.
python -m venv .venv && source .venv/bin/activate
python -m pip install caliper-ai
```

PyPI distribution name is `caliper-ai`. Command and Python import are
both `caliper`. `uvx caliper` (without `--from`) hits a different,
unrelated package; always use `--from caliper-ai caliper`. If
`uvx --from caliper-ai caliper --version` shows an older version on your
machine, uv is reusing a persistent tool install; run `uv tool upgrade
caliper-ai` or use the isolated command above.

If you see `error: No virtual environment found` from `uv pip
install`, that command only installs into an active venv. Use one of
the four paths above instead.

If you see `error: externally-managed-environment` from system `pip3`
on macOS or recent Debian, the same fix applies: pick a venv-based
or tool-based path. PEP 668 blocks system installs on purpose.

## First sixty seconds

```bash
caliper                              # rolling 7 / 30 / 90 summary
caliper doctor                       # verifies your local setup
caliper daily --lookback-days 7      # daily rollup
caliper project --lookback-days 30   # which projects cost what
caliper shape --lookback-days 7      # tool-use & session shape (Claude Code)
caliper insights                     # ranked signals with next commands
caliper advise                       # grouped model/tier recommendations
caliper evidence                     # explain how trustworthy the numbers are
caliper dashboard                    # opens a self-contained HTML dashboard
caliper dashboard --demo             # opens a synthetic dashboard, no log reads
```

The first run parses everything and writes a sidecar parse cache. Later runs
reuse it. The cache stores normalized usage records and parser metadata on
your machine; default output still redacts prompts, paths, git identifiers,
and session identifiers. Pass `--disable-parse-cache` when you want to bypass
the cache, or delete the directory named by `CALIPER_CACHE_DIR`.

If `caliper` shows no data after the first run, your AI tools probably
write logs to a non-default location. Run `caliper doctor` — it lists
which tools were detected and what's missing.

## Interactive workspace

If you prefer to live inside the data, `caliper-ai` also ships with an
interactive Textual workspace:

```bash
caliper tui                              # against your real logs
caliper tui --demo                       # synthetic fixture, zero disk reads
```

The TUI is a single Python process built on
[Textual](https://github.com/Textualize/textual). It reuses every pure
module the classic CLI uses (parser, pricing, aggregation, windows,
insights) and adds only presentation: a Home overview with cost cards,
primary/secondary limit panels, the insights feed, and recent sessions.
The workspace reuses the same parser, pricing, aggregation, windows, and
insights modules as the CLI. Offline by default. No login. No telemetry. The
classic CLI is the stable surface; the Textual workspace is an additional
entry point.

## Static HTML dashboard

```bash
caliper dashboard
caliper dashboard --demo
caliper dashboard --output ~/caliper.html --open
```

One self-contained HTML file. Run `caliper dashboard` to open it directly in
your default browser. Use `--output` when you want to keep a named file, or
`--stdout` when you are piping raw HTML. Email it to your manager. Drop it on
a USB drive. **No external resources** — no CDN, no
`<script src>`, no `<link rel="stylesheet">`, no `fetch(`, no
`@import`. The privacy invariant is tested in CI:

```bash
grep -E "://|<script|<link" ~/caliper.html  # → no matches
```

The dashboard reports the same numbers the CLI does, plus session
shape (what kind of work the AI did), per-day dominant work pattern,
period-over-period delta chips, a daily-mean reference line on the cost
chart, a forecast band, and an evidence audit table.

Flags:

| Flag | Default | Meaning |
|---|---|---|
| `--theme {dark,light,print}` | `dark` | Visual theme. Light is Stripe-receipt clean; print collapses to ink-on-paper. |
| `--density {comfortable,compact}` | `comfortable` | Row density. |
| `--demo` | off | Render built-in synthetic data instead of reading local logs. |
| `--no-deltas` | off | Skip the period-over-period parse pass (one fewer aggregate). |
| `--show-paths` | off | Show full project paths instead of basenames. |
| `--output PATH` | temp file | Write the dashboard to a named HTML file. |
| `--open` | auto without `--output` | Open the generated file in your default browser. |
| `--stdout` | off | Print raw HTML instead of opening a browser. |

## Privacy is a constraint, not a feature

- No login, ever.
- No upload, ever.
- No telemetry, ever.
- Prompts and titles are redacted in default output. Pass `--show-prompts`
  if you want them.
- Absolute local paths, repo origins, git identifiers, and session identifiers
  are redacted in machine-readable output by default. Pass `--show-paths` only
  when you explicitly want those identifiers in JSON.
- Default usage analysis makes no network calls. Pricing refresh and GitHub
  CLI PR resolution require explicit flags. The privacy invariant is tested.

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
- Report evidence is graded as `exact`, `estimated`, `partial`, or
  `unsupported`. JSON reports carry the evidence metadata; table and
  receipt outputs surface the status so budget numbers do not look more
  certain than the local logs allow.

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
Budget periods are current local calendar periods: daily means local
midnight to now, weekly means the current local week to now, and monthly
means the current local month to now.

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
The Prometheus exporter is a local `/metrics` process for live scraping.
The Grafana exporter prints a static dashboard JSON you can import or keep
under source control. The optional `[prom]` extra brings
`prometheus-client` in.

| Exporter | Usage data? | Output | Source flags |
|---|---:|---|---|
| `export receipt` | yes | Markdown or HTML receipt for one month | accepts session/config/rate flags |
| `export prometheus` | yes | local `/metrics` server | accepts session/config/rate flags |
| `export grafana` | no | static dashboard JSON template | does not read usage logs |

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
Yes, when Cursor's local data includes token-bearing records. Some Cursor
files are transcript-only and do not carry per-event token counts. `caliper
doctor` flags those so Cursor coverage is visible instead of being implied.

**Why not just read the vendor dashboards?**
Because the dashboards are per-vendor and per-account. They do not know
which commit, which PR, or which project spent the money. They also
require a login, which is the wrong fit for offline-only workflows.

**How accurate are the costs?**
As accurate as the rate card. The rate card ships embedded with a
`checked` date and warns when it ages. You can pin a local rate card to
match an invoice exactly. Run `caliper evidence` when you need to know
whether usage, model, tier, pricing, project, and git attribution are exact
or inferred for the active window.

**What about the Anthropic admin API or the OpenAI usage API?**
Out of scope on purpose. Caliper is local-only. The trade-off is named:
you get nothing if the vendor never wrote a log to disk.

**How is this different from Helicone / Langfuse / OpenLLMetry?**
Those are hosted proxies or telemetry pipelines. Your prompts flow
through their infrastructure. Caliper does not sit on the request path;
it reads the logs your tools already wrote to your disk. No proxy, no
SaaS, no shared infrastructure. If you need a multi-tenant hosted
dashboard, those products are the right choice. If you want a number
per PR without uploading anything, this is.

**Is the cache hit rate real?**
Yes. Cached input tokens are billed at a different rate than fresh
input tokens — the parser tracks them separately when the vendor's log
exposes them (Claude Code: `cache_read_input_tokens` /
`cache_creation_input_tokens`; Codex: `cached_input_tokens`). Run
`caliper evidence` to see how each dimension is graded.

**Can I self-host the export?**
Yes. The Prometheus and Grafana exporters are local processes. The
HTML dashboard / receipt are files you can email yourself.

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
