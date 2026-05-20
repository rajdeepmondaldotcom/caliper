<div align="center">

# Caliper

### The local cost ledger for AI-assisted development.

Run one command. Get a private browser dashboard showing what your AI coding
actually cost by project, model, vendor, pull request, and time window.

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

---

## What Caliper Is

Caliper reads the local logs already written by OpenAI Codex CLI, Claude Code,
Cursor, and Aider. It normalizes them into one event shape, applies explicit
pricing, and gives you cost reports you can actually use:

- What did this pull request cost?
- Which project is driving the bill?
- Which model or vendor is expensive?
- How much did cache reuse save?
- Are these numbers exact, estimated, partial, or unsupported?
- Can I inspect all of this without uploading prompts anywhere?

The answer stays on your machine.

## The First Command

```bash
caliper dashboard
```

Caliper opens a self-contained HTML dashboard in your browser. It reads your
real local logs, writes a temporary local HTML file, and uses no external
resources. If no logs are found, the dashboard still opens and `caliper doctor`
tells you exactly what Caliper could and could not detect.

For terminal output:

```bash
caliper overview
caliper project --lookback-days 30
caliper pr 42
caliper evidence
caliper doctor
```

## Why It Exists

AI coding tools are good at spending tokens and bad at explaining the bill.
Vendor dashboards are per-tool, per-account, and behind logins. They do not
know your local git history, project folders, pull requests, cached-input share, or
evidence quality.

Caliper is the missing local ledger.

| What you need to know | What Caliper reads |
|---|---|
| PR cost | Local git attribution and session metadata. |
| Project cost | Local working directories and vendor project records. |
| Model mix | Model names and service tiers recorded by the tools. |
| Cache savings | Cached input and cache creation token fields where vendors expose them. |
| Confidence | Evidence grades for usage, model, tier, pricing, project, and git attribution. |

## Install

Requires Python 3.11 or newer.

```bash
# Persistent global tool. Recommended.
uv tool install caliper-ai

# Update later.
uv tool upgrade caliper-ai
```

One-off run:

```bash
uvx --isolated --from caliper-ai caliper dashboard
```

Other install paths:

```bash
# pipx
pipx install caliper-ai
pipx upgrade caliper-ai

# venv + pip
python -m venv .venv
source .venv/bin/activate
python -m pip install caliper-ai
```

The PyPI package is `caliper-ai`; the command is `caliper`.

Use this form for `uvx`:

```bash
uvx --isolated --from caliper-ai caliper
```

Avoid this:

```bash
uvx caliper
```

That can resolve a different package. If a just-published version exists on
PyPI but `uv` cannot find it yet, the resolver cache or PyPI simple index is
stale. Wait a moment, then run:

```bash
UV_NO_CACHE=1 uv tool install --force caliper-ai
```

## What You Get

| Surface | Command | Purpose |
|---|---|---|
| Browser dashboard | `caliper dashboard` | Open the local HTML report. |
| Overview | `caliper overview` | Rolling 7 / 30 / 90 day spend. |
| PR receipt | `caliper pr 42` | Cost attributed to one pull request. |
| Git range receipt | `caliper pr --git-range main...branch` | Cost for an explicit local range. |
| Project rollup | `caliper project` | Spend by repository or folder. |
| Model rollup | `caliper models` | Spend by model and vendor. |
| Evidence report | `caliper evidence` | How trustworthy each dimension is. |
| Doctor | `caliper doctor` | Local setup and data coverage. |
| Insights | `caliper insights` | Ranked findings with next commands. |
| TUI | `caliper tui` | Interactive terminal workspace. |
| Budgets | `caliper budgets check` | CI-friendly warning and breach exits. |

## Example Output

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
caliper project --lookback-days 30
```

```text
payments-api       4 models     $81
frontend-lab       4 models     $63
internal-tools     3 models     $43
```

```bash
caliper insights
```

```text
High cache reuse: 72.4% of input tokens were recorded as cached input,
with an estimated $612 cache benefit. Keep prompts and file context stable
to preserve cache reads.
```

Names and numbers above are sanitized examples.

## PR Receipts

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

By default, `caliper pr <N>` uses local fetched pull refs and filters events
whose recorded git SHA matches the PR commits.

If you want Caliper to ask the GitHub CLI for PR commit resolution, opt in:

```bash
caliper pr 42 --allow-network
```

Or pass a local range:

```bash
caliper pr --git-range main...feature-branch
```

Every receipt carries evidence grades. Missing git attribution is surfaced as
partial evidence instead of being silently treated as exact.

## Dashboard

```bash
caliper dashboard
```

The dashboard is one local HTML file:

- opens in your default browser
- contains no CDN references
- contains no external stylesheet links
- contains no external script tags
- makes no fetches
- can be saved, emailed, or archived as a standalone artifact

Useful variants:

```bash
caliper dashboard --output ~/caliper.html --open
caliper dashboard --theme light
caliper dashboard --theme print --output ~/caliper-print.html
caliper dashboard --stdout > caliper.html
```

Dashboard flags:

| Flag | Default | Meaning |
|---|---|---|
| `--theme {dark,light,print}` | `dark` | Visual theme. |
| `--density {comfortable,compact}` | `comfortable` | Row density. |
| `--no-deltas` | off | Skip the period-over-period comparison pass. |
| `--show-paths` | off | Show full project paths instead of basenames. |
| `--output PATH` | temp file | Write the dashboard to a named HTML file. |
| `--open` | auto without `--output` | Open the generated file in your browser. |
| `--stdout` | off | Print raw HTML for scripts and pipes. |

The privacy invariant is tested in CI:

```bash
grep -E "://|<script|<link" ~/caliper.html  # no matches
```

## Trust Model

Caliper is built around a hard local boundary.

| Boundary | Default |
|---|---|
| Login | none |
| Upload | none |
| Telemetry | none |
| Daemon | none |
| Request proxy | none |
| Network calls during usage analysis | none |
| Prompt output | redacted |
| Absolute paths | redacted |
| Git identifiers | redacted in machine-readable output |
| Pricing refresh | explicit network-enabled command |
| GitHub PR lookup | explicit `--allow-network` |

If you want to inspect the boundary, start here:

- [src/caliper/parser.py](src/caliper/parser.py)
- [src/caliper/parse_cache.py](src/caliper/parse_cache.py)
- [src/caliper/network.py](src/caliper/network.py)
- [src/caliper/dashboards/html.py](src/caliper/dashboards/html.py)

## Accuracy and Evidence

Caliper does not pretend every local log is perfect. It reports what the
evidence supports.

- Costs use `Decimal`.
- Cached input, cache creation, output, and reasoning tokens are tracked
  separately when vendors expose them.
- Long-context multipliers are applied per model.
- Unknown pricing is surfaced as a warning, not silently guessed.
- Cursor files without per-event token counts are reported by `caliper doctor`.
- Evidence is graded as `exact`, `estimated`, `partial`, or `unsupported`.

Use these before treating a number as a budget fact:

```bash
caliper evidence
caliper doctor
caliper rates show
```

Refresh public pricing catalogs only when you explicitly want network access:

```bash
caliper rates refresh --allow-network
```

Pin a local rate card when you need to match an invoice:

```bash
caliper daily --rate-card-file ./rates.json
```

## Supported Sources

| Source | What Caliper reads |
|---|---|
| OpenAI Codex CLI | Local session logs, state DB metadata, model and token fields. |
| Claude Code | Project JSONL logs, tool-use shape, cache token fields. |
| Cursor | Local token-bearing records when available. |
| Aider | Local chat history and usage records. |

Some vendor files are transcript-only or missing token details. Caliper keeps
those gaps visible in `caliper doctor` and `caliper evidence`.

## Budgets in CI

Caliper exits with stable codes, so CI can warn or fail on usage budgets.

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

Budget periods are current local calendar periods: daily means local midnight
to now, weekly means the current local week to now, and monthly means the
current local month to now.

## Exports

```bash
# Every grouped report now supports --format html — emits a self-contained,
# share-safe dashboard page (no CDN, no JS deps, inline styles).
caliper daily   --format html --out daily.html
caliper models  --format html --out models.html --no-share-safe   # local-only
caliper monthly --format html > may.html

# Monthly receipt + dedicated dashboard + integrations.
caliper export receipt --receipt-month 2026-05 --receipt-format html
caliper export prometheus --metrics-port 9090
caliper export grafana
```

| Exporter | Reads usage logs? | Output |
|---|---:|---|
| `<command> --format html` | yes | Self-contained dashboard for any grouped command |
| `dashboard` | yes | Polished interactive dashboard (full chrome) |
| `export receipt` | yes | Markdown or HTML monthly receipt |
| `export prometheus` | yes | Local `/metrics` server |
| `export grafana` | no | Static Grafana dashboard JSON |

### Loading visibility

Every long-running command honors `--progress` / `--quiet`. The
`--progress` flag forces a multi-stage stderr widget on (parse →
aggregate → analyse → render → write) so users never wonder what the
CLI is doing — even when piping JSON or writing to a file. `--quiet`
silences progress entirely. Without either flag, progress
auto-activates only for the classic TTY + table path, preserving the
existing default.

The optional Prometheus dependency is available as an extra:

```bash
pipx install "caliper-ai[prom]"
```

## Interactive Workspace

```bash
caliper tui
```

The TUI is built with Textual and reuses the same parser, pricing,
aggregation, evidence, and insight modules as the CLI. It adds an interactive
home screen, cost cards, limit panels, insight feed, recent sessions, models,
forecasting, receipts, and doctor output.

The classic CLI remains the stable automation surface. The TUI is the place
to explore.

## Configuration

```bash
caliper init
```

That writes a commented `.caliper.toml`.

Common environment overrides:

| Variable | Meaning |
|---|---|
| `CALIPER_CACHE_DIR` | Parse-cache location. |
| `CALIPER_DATA_DIR` | Pricing-catalog location. |
| `CODEX_HOME` | OpenAI Codex CLI data location. |
| `CLAUDE_CONFIG_DIR` | Claude Code data location. |

## Python API

```python
from caliper.aggregation import aggregate_total
from caliper.config import build_options
from caliper.parser import load_usage

options = build_options(days=7)
result = load_usage(options)
total = aggregate_total(result, options)

print(total.totals.total_tokens)
```

The public import path is `caliper`. Core dataclasses are frozen.

## Who It Is For

- Developers paying their own AI bill who want line items instead of a shrug.
- Engineering managers who need cost per PR, not per vendor account.
- Teams with strict data policies that cannot upload prompts to another
  analytics service.
- Anyone trying to understand whether model choice, service tier, cache reads,
  or project shape is driving spend.

## Who It Is Not For

- Teams that want a hosted dashboard with sign-in.
- Teams that need a request proxy or prompt observability platform.
- Teams whose tools do not write token-bearing local logs.
- People who want Caliper to call vendor admin APIs by default.

Caliper is intentionally local-first. If you need a multi-tenant SaaS
dashboard, use one. If you want a receipt from the evidence already on your
machine, use Caliper.

## FAQ

**Does it work with Cursor today?**

Yes, when Cursor's local data includes token-bearing records. Some Cursor
files are transcript-only and do not carry per-event token counts. `caliper
doctor` reports those files so coverage is explicit.

**Why not just use the vendor dashboards?**

Vendor dashboards are per-vendor and per-account. They do not know which PR,
commit, or local project produced the spend. They also require a login.

**How accurate are the costs?**

As accurate as the local logs and rate card allow. Run `caliper evidence` to
see exactly which dimensions are exact, estimated, partial, or unsupported.

**Does Caliper upload prompts?**

No. Default usage analysis is local-only and redacts prompt-like fields from
normal output.

**Can Caliper refresh pricing?**

Yes, but only when you ask for it with an explicit network-enabled command.
The package also ships an embedded rate card with a checked date.

**How is this different from Helicone, Langfuse, or OpenLLMetry?**

Those are hosted proxies or telemetry pipelines. They are useful if you want
request-path observability. Caliper does not sit on the request path. It reads
local logs after the fact.

**Is there a hosted version?**

No. There is no hosted version on the roadmap.

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

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution surface:
rate-card updates, new vendor parsers, schema changes, and release hygiene.

## Who Built This

I am [Rajdeep Mondal](https://github.com/rajdeepmondaldotcom). I built Caliper
because I had a four-figure AI coding bill, a strong hunch about which work
caused it, and no offline way to prove it.

The first version paid for itself in one PR review.

## License

MIT. See [LICENSE](LICENSE).
