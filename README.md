<div align="center">

# Caliper

**Measure every line of AI-written code.**

Offline-first usage, cost, and ROI intelligence for AI coding tools.

[![CI](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml/badge.svg)](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/caliper-ai.svg)](https://pypi.org/project/caliper-ai/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

## What is Caliper?

Caliper is a single command that turns the trail your AI coding tools already
leave on your machine into a clear, finance-grade record of what you actually
spent and what you actually got.

- **Local by default.** No login, no upload, no billing scrape, no telemetry.
- **Per-session, per-project, per-model, per-tier.** Tokens, credits,
  API-equivalent dollars, cache savings, rate-limit windows, burn rate.
- **Live TUI, statusline, forecasts, budgets, receipts, Prometheus, Grafana.**
- **Vendor-neutral architecture.** Ships today with OpenAI Codex CLI
  coverage; Claude Code, Cursor, Aider, and Copilot parsers land in the next
  releases. Same record format, same reports, same pricing engine.

If you pay for AI coding tools and cannot answer *"what did the last PR cost?"*
or *"is Opus actually carrying its weight on this repo?"* — Caliper is the
fastest path to an honest answer.

---

## Install

Requires Python 3.11+.

```bash
# Zero-install run
uvx caliper-ai

# Persistent install
uv tool install caliper-ai
caliper

# pipx
pipx install caliper-ai
caliper

# pip
python -m pip install caliper-ai

# Prometheus exporter extra
uv tool install 'caliper-ai[prom]'

# Homebrew
brew install rajdeepmondaldotcom/tap/caliper
```

The `codex-meter` command remains available as an alias for users upgrading
from the original release. Both binaries dispatch to the same CLI.

---

## 30 seconds in

```bash
caliper                              # 7 / 30 / 90 day overview
caliper doctor                       # sanity-check local data and assumptions
caliper live                         # watch usage while you work
caliper statusline                   # one-line snapshot for prompts and editors
caliper project --days 30            # per-repo activity and cost
caliper models --days 30             # model and tier mix
caliper forecast --days 14           # linear + EWMA projection with ±1σ band
caliper compare --a "last 7 days" --b "previous 7 days"
caliper whatif --tier standard       # what-if pricing scenarios
caliper export receipt --month 2026-05 --format html > receipt.html
```

First run parses local session files. Later runs use a sidecar parse cache.
Use `--no-parse-cache` when debugging parser behavior.

---

## Why it exists

AI coding tools changed how software ships. Every paid developer now burns
between $20 and $2,000 a month across Codex, Claude Code, Cursor, Copilot,
Aider, and friends. Two questions are getting louder every week:

1. **What did this actually cost?** Vendor dashboards show what *they* charged
   you. They do not show what each PR, each repo, or each session actually
   consumed — and they certainly do not show it across vendors in one view.
2. **Did the spend ship code?** Tokens are not value. Caliper makes the link
   between AI spend and the code that left your machine inspectable.

Caliper is the local instrument that answers both. The data already exists on
your laptop. Caliper turns it into evidence you can audit, export, share with
finance, or push to Prometheus.

This is not a vendor billing ledger. It is local usage intelligence.

---

## What you get

### Reports

| Report | Command |
| --- | --- |
| Rolling 7 / 30 / 90 day overview | `caliper` |
| Daily / weekly / monthly | `caliper daily`, `weekly`, `monthly` |
| Per session | `caliper session --top 20` |
| Per project / repo | `caliper project --days 30` |
| Per model and tier | `caliper models --days 30` |
| Recent events | `caliper tail --n 20` |
| Rate-limit windows | `caliper limits` |
| Statusline snapshot | `caliper statusline` |
| Insights (cache, concentration, tier confidence, trend) | `caliper insights` |
| Forecast with ±1σ band and ETA-to-cap | `caliper forecast --days 14` |
| Window comparison | `caliper compare --a "last 7 days" --b "previous 7 days"` |
| What-if pricing | `caliper whatif --tier standard` |
| Budgets (warn/breach) | `caliper budgets check` |
| Receipt (HTML / Markdown) | `caliper export receipt --month 2026-05 --format html` |
| Prometheus exporter | `caliper export prometheus --port 9090` |
| Grafana dashboard JSON | `caliper export grafana > dashboard.json` |

Every grouped report supports `--format table|json|csv|markdown`,
`--output FILE`, `--since YYYY-MM-DD`, `--days N`, and `--top N`.

JSON exports include a `projects` inventory for the window and row-level
`model_breakdowns` — paths, session counts, first/last seen, models, tiers,
model source/fallback flags, git branches/remotes when Codex recorded them,
plus the same token and cost fields as the primary breakdown.

### Live view

```bash
caliper live
```

A three-panel Rich TUI: today's usage, trailing 7-day usage, 5-hour and weekly
rate-limit windows, burn rate, and ETA-to-100% when enough samples exist.

| Key | Action |
| --- | --- |
| `q` | Quit |
| `?` | Help |
| `r` | Refresh |
| `p` | Pause |

### Statusline

```bash
caliper statusline
caliper statusline --format json
```

One compact line for shell prompts, editor hooks, and scripts: latest
model/tier, top project, today's credits and API-equivalent dollars,
trailing 7-day credits, 5-hour and weekly reset windows, cache ratio, and
pricing status.

### Budgets that gate CI

```bash
caliper init
```

```toml
[budgets]
daily_credits = 25000
weekly_credits = 100000
monthly_credits = 400000
weekly_api_dollars = 50.0
```

```bash
caliper budgets check
```

Exit codes are designed for CI:

| Exit | Meaning |
| ---: | --- |
| `0` | ok |
| `1` | warning |
| `2` | breached or failed |

### Receipts you can hand to finance

```bash
caliper export receipt --month 2026-05 --format markdown
caliper export receipt --month 2026-05 --format html > receipt.html
```

Receipts redact local session and project labels by default. Use
`--show-sensitive` only for private artifacts.

### Prometheus and Grafana

```bash
caliper export prometheus --host 127.0.0.1 --port 9090
caliper export grafana > dashboard.json
```

Exposes credits, burn rate, rate-limit window percent, event count,
long-context event count, and tokens by model/tier/kind. Drop the dashboard
JSON into Grafana and you have a real-time view in under a minute.

---

## Data sources

Caliper reads:

- `~/.codex/sessions/**/*.jsonl`
- `~/.codex/state_5.sqlite`
- `~/.codex/config.toml`

If `CODEX_HOME` is set, those defaults move under that directory, matching
Codex itself. Explicit `--session-root`, `--state-db`, `--codex-config`, and
config file paths still take precedence.

Workspace attribution is local and evidence-based. For each usage event,
Caliper uses:

1. JSONL `turn_context.cwd`
2. SQLite `threads.cwd`
3. `Unknown Project`

Normal reports never touch the network. The only networked command is
explicit:

```bash
caliper rates refresh --allow-network
```

This writes a local pricing-source audit snapshot (observed token rates, fast
multipliers, long-context rules, discrepancies). It does not rewrite the
embedded rate card.

---

## Accuracy is the point

The hard part is not adding tokens. It is making assumptions visible.

Caliper:

- Tracks cached input tokens separately and rebates them at the cached rate.
- Applies per-model long-context input/output multipliers when the model card
  declares a `long_context` rule.
- Uses **exact Decimal math** internally; floats only appear at output
  boundaries.
- Reports whether each event's service tier came from logs, config, an
  override file, or an assumption — with per-source counts in JSON output.
- Surfaces pricing as **exact**, **estimated**, or **unpriced** so a
  fallback never silently masquerades as a billing receipt.

### Model identity provenance

JSON exports record whether each event's model came from JSONL
`turn_context`, SQLite thread metadata, or the configured default model.
When the default model is used because a legacy session recorded tokens
without model metadata, those events are marked as fallback model events
and pricing is treated as estimated.

### Subscription plans are treated as metadata, not pricing magic

Caliper preserves the raw `plan_type`, adds normalized subscription plan
details for Free, Go, Plus, Pro, Business, Enterprise, Edu, Health, Gov, and
ChatGPT for Teachers, and uses the logged `codex` rate-limit bucket for
remaining-window math when multiple buckets are present. Free/Go promotional
access and Enterprise-family legacy-rate-card ambiguity surface as warnings
instead of being guessed.

Reasoning tokens are only billed separately when the token log shows they
are not already included in output tokens. No double counting.

### Service-tier precedence

1. `--service-tier standard|fast`
2. `--tier-overrides overrides.json`
3. logged tier
4. current `~/.codex/config.toml`
5. `--unknown-service-tier`

Inspect or override pricing:

```bash
caliper rates show
caliper rates show --format json
caliper daily --rates-file ./rates.json
```

Schemas:

- [`schemas/rates.schema.json`](schemas/rates.schema.json)
- [`schemas/tier-overrides.schema.json`](schemas/tier-overrides.schema.json)

---

## Privacy

Default posture is local and conservative.

- Reports read local files only.
- Prompt and session labels are redacted unless explicitly requested.
- Receipts hide full session IDs and project paths by default.
- JSON, CSV, Markdown, and HTML exports may still contain local metadata
  (paths, git remotes) when those fields are present in the source data.

Treat exports as sensitive unless you made them to be shared.

---

## Roadmap

Caliper 1.0 ships with full OpenAI Codex CLI coverage. The pipeline ahead:

| Milestone | What lands |
| --- | --- |
| 1.1 | Claude Code parser (`~/.claude/projects/**/*.jsonl`) — same record shape, same reports |
| 1.2 | Cursor + Aider parsers; cross-vendor model and tier normalization |
| 1.3 | Per-PR / per-commit attribution via local `git log` join — every PR carries its real AI cost |
| 1.4 | Model-arbitrage advisor — flags spend where a smaller model would have shipped the same work |
| 1.5 | VS Code / Cursor / Zed extension surfacing live cost in the editor |
| 2.0 | Opt-in team aggregator — workspace rollups, Slack/Linear digests, finance export |

The local CLI stays free, MIT, and offline-first. Team and enterprise
features are strictly opt-in and operate on data you explicitly export.

---

## Development

```bash
uv sync --dev
uv run ruff check .
uv run ruff format --check .
PYTHONWARNINGS=error::ResourceWarning uv run pytest
uv run pytest --cov=src/caliper --cov-report=term
uv run python -m build
```

Smoke test against your own logs:

```bash
uv run caliper doctor
uv run caliper overview
uv run caliper rates show
```

---

## License

MIT. See [LICENSE](LICENSE).
