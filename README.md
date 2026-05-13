<div align="center">

# Caliper

**Measure every line of AI-written code.**

Offline-first usage, cost, and ROI intelligence for AI coding tools.

[![CI](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml/badge.svg)](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/caliper-ai.svg)](https://pypi.org/project/caliper-ai/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-88%25-brightgreen.svg)](#development)

```bash
uvx caliper-ai
```

That is the whole demo. Run it once. The next paragraph will make sense.

</div>

---

## The 30-second pitch

A typical engineer using AI coding tools today burns somewhere between **$20
and $2,000 a month** across Codex, Claude Code, Cursor, Copilot, and Aider.
Their employer often pays a multiple of that. Nobody — not the developer,
not the eng lead, not finance — can answer two questions with evidence:

1. **What did this PR actually cost?**
2. **Did the spend ship code?**

Vendor dashboards do not answer either. They show what *they* charged you,
in *their* unit, for *their* tool, on *their* timeline. They are not built
to be honest about waste, and they cannot see across vendors.

Caliper does. It reads the trail your AI coding tools already leave on your
laptop, joins it with local pricing, and turns it into the kind of evidence
you can hand to finance, push to Prometheus, or commit alongside the PR.

**No login. No upload. No telemetry. No vendor lock-in.** Your data never
leaves the machine unless you explicitly export it.

---

## What it looks like

```text
$ caliper
Caliper • 7d / 30d / 90d • OpenAI Codex CLI
─────────────────────────────────────────────────────────────────
                         7 days      30 days     90 days
─────────────────────────────────────────────────────────────────
 events                  1,284       4,901       14,302
 input tokens            12.4 M      48.7 M      141.2 M
   cached                 8.9 M      35.1 M      102.7 M     (72%)
 output tokens            1.1 M       4.4 M        12.9 M
 reasoning tokens         0.3 M       1.3 M         3.7 M
 API-equiv $             $48.20     $192.30      $562.10
 credits used            81,420    312,810       907,440
 top project              monorepo (61%)
 top model                gpt-5.4 standard (44%)
 pricing status           exact
 service-tier source      log: 1,109 · config: 175

 burn (last 6h)           19,300 credits/hr
 5h window                42% used · resets in 2h 11m
 weekly window            61% used · resets in 3d 04h

Run  caliper insights   for cache-savings, tier-confidence, and concentration hints.
Run  caliper forecast   for a 14-day projection with ±1σ band and ETA-to-cap.
Run  caliper doctor     to validate your local data and assumptions.
```

```text
$ caliper budgets check
[ok]    daily_credits   12,310 / 25,000   ( 49% )
[warn]  weekly_credits  87,420 / 100,000  ( 87% )   → review burn at  caliper forecast
[ok]    monthly_credits 312,810 / 400,000 ( 78% )
exit 1   # CI-friendly: 0 ok / 1 warn / 2 breach
```

```text
$ caliper export receipt --month 2026-05 --format markdown | head
# Caliper receipt — 2026-05
Generated 2026-05-31 23:59 IST · pricing: exact · vendor: openai-codex

| Total                  | Value       |
| ---------------------- | ----------- |
| Events                 | 4,901       |
| Input tokens (cached)  | 35.1 M (72%)|
| API-equivalent $       | $192.30     |
| Credits (standard)     | 312,810     |
| Cache savings $        | $98.40      |
```

> Sample output — numbers above are illustrative.
> Run `caliper` against your own `~/.codex/sessions/` to see real ones.

---

## Why this is the right tool for the job

| | Vendor billing dashboard | `ccusage` / per-vendor scripts | **Caliper** |
| --- | :---: | :---: | :---: |
| Multi-vendor in one view | no | no | yes (roadmap) |
| Per-PR / per-repo attribution | no | partial | yes (roadmap) |
| Cache savings broken out | no | no | yes |
| Service-tier provenance | no | no | yes |
| Decimal-exact pricing math | no | no | yes |
| Forecast + ±1σ band + ETA-to-cap | no | no | yes |
| Budgets with CI-gradable exit codes | no | no | yes |
| Prometheus + Grafana out of the box | no | no | yes |
| Live TUI for a tmux pane | no | no | yes |
| Works offline. Stays offline. | n/a | yes | yes |
| Local privacy by default | no | yes | yes |

Caliper is not trying to replace vendor billing. It is the local instrument
that sits next to it — the kind of evidence you would want before you
escalated a spend conversation, the kind of receipt you would want before
you wrote off AI coding as an expense, the kind of dashboard you would want
before you greenlit Opus in CI.

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

# With Prometheus exporter
uv tool install 'caliper-ai[prom]'

# Homebrew
brew install rajdeepmondaldotcom/tap/caliper
```

The PyPI distribution name is `caliper-ai`. The Python import path and the
CLI binary are both `caliper`. The `codex-meter` command is preserved as a
permanent alias for users upgrading from the original release.

---

## 30 seconds in

```bash
caliper                              # 7 / 30 / 90 day overview
caliper doctor                       # sanity-check local data and assumptions
caliper live                         # watch usage while you work
caliper statusline                   # one-line snapshot for prompts and editors
caliper project --days 30            # per-repo activity and cost
caliper models --days 30             # model and tier mix
caliper insights                     # cache-savings, tier confidence, concentration
caliper forecast --days 14           # linear + EWMA with ±1σ band
caliper compare --a "last 7 days" --b "previous 7 days"
caliper whatif --tier standard       # what-if pricing scenarios
caliper budgets check                # CI-gradable warn/breach
caliper export receipt --month 2026-05 --format html > receipt.html
caliper export prometheus --port 9090
caliper export grafana > dashboard.json
```

First run parses local session files. Later runs use a sidecar parse cache.
Use `--no-parse-cache` while debugging parser behavior.

---

## What you get, in full

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

A three-panel Rich TUI: today's usage, trailing 7-day usage, 5-hour and
weekly rate-limit windows, burn rate, and ETA-to-100% when enough samples
exist.

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

## Accuracy is the product

The hard part is not adding tokens. It is making assumptions visible.

Caliper:

- Tracks cached input tokens separately and rebates them at the cached rate.
- Applies per-model long-context input/output multipliers when the model
  card declares a `long_context` rule.
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

### Subscription plans are metadata, not pricing magic

Caliper preserves the raw `plan_type`, adds normalized subscription plan
details for Free, Go, Plus, Pro, Business, Enterprise, Edu, Health, Gov,
and ChatGPT for Teachers, and uses the logged `codex` rate-limit bucket for
remaining-window math when multiple buckets are present. Free/Go
promotional access and Enterprise-family legacy-rate-card ambiguity surface
as warnings instead of being guessed.

Reasoning tokens are billed separately only when the token log shows they
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

## Data sources

Today, Caliper reads:

- `~/.codex/sessions/**/*.jsonl`
- `~/.codex/state_5.sqlite`
- `~/.codex/config.toml`

If `CODEX_HOME` is set, those defaults move under that directory, matching
Codex itself. Explicit `--session-root`, `--state-db`, `--codex-config`,
and config file paths still take precedence.

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

This writes a local pricing-source audit snapshot (observed token rates,
fast multipliers, long-context rules, discrepancies). It does not rewrite
the embedded rate card.

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

Caliper 0.4 ships with full OpenAI Codex CLI coverage and the vendor-neutral
record format that the next milestones build on.

| Milestone | What lands |
| --- | --- |
| **0.5** | Claude Code parser (`~/.claude/projects/**/*.jsonl`) — same record shape, same reports, same pricing engine |
| **0.6** | Cursor + Aider parsers; cross-vendor model and tier normalization |
| **0.7** | Per-PR / per-commit attribution via local `git log` join — every PR carries its real AI cost |
| **0.8** | Model-arbitrage advisor — flags spend where a smaller model would have shipped the same work |
| **0.9** | VS Code / Cursor / Zed extension surfacing live cost in the editor |
| **1.0** | Public API freeze; cross-vendor surface considered stable. Multi-vendor parser set ships together. |
| **post-1.0** | Opt-in team aggregator — workspace rollups, Slack/Linear digests, finance export. Local CLI stays free, MIT, and offline-first. |

Caliper will not reach `1.0` until at least three vendor parsers (Codex,
Claude Code, Cursor) ship together. That is the bar for calling the public
surface stable.

---

## Versioning

Caliper follows **[Semantic Versioning](https://semver.org/)** with a
deliberately conservative pre-1.0 cadence:

- `0.x.y` — the public API may still move between minor versions while the
  cross-vendor surface stabilizes. Every release documents breakage in the
  changelog and provides a one-step upgrade path.
- `1.0.0` — reserved for the release where the CLI surface, the
  vendor-neutral record format, and the multi-vendor parser set are
  considered frozen.

Read the full record in [CHANGELOG.md](CHANGELOG.md).

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

The coverage gate is **85% minimum** in CI; the suite currently sits at
**88%+** across 190+ tests on Python 3.11, 3.12, and 3.13.

Smoke test against your own logs:

```bash
uv run caliper doctor
uv run caliper overview
uv run caliper rates show
```

---

## Project ethos

Caliper is built and maintained by
[Rajdeep Mondal](https://github.com/rajdeepmondaldotcom) as a personal
open-source project. It is intentionally:

- **Local-first.** Your usage data is yours. It does not leave your
  machine.
- **Vendor-neutral.** No tool in this space should depend on a single AI
  vendor staying still.
- **Decimal-correct.** When the unit is money, the math has to be exact.
- **Honest about uncertainty.** When pricing is estimated, the report says
  so. When a tier is assumed, the report says so. When a model came from a
  fallback, the report says so.
- **Conservative in versioning.** No `1.0` until the public surface and
  the multi-vendor parser set can carry the weight of that promise.

If Caliper makes your AI spend visible, useful, or accountable in a way it
was not before, please
[open an issue](https://github.com/rajdeepmondaldotcom/caliper/issues)
with what worked and what did not. That is the feedback loop that drives
the roadmap.

---

## License

MIT. See [LICENSE](LICENSE).
