<div align="center">

# Caliper

### Datadog for AI coding spend.

The open-source, local-first instrument that turns the trail your AI coding
tools leave on your laptop into per-PR, per-repo, per-model evidence of what
you actually spent and what you actually shipped.

[![CI](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml/badge.svg)](https://github.com/rajdeepmondaldotcom/caliper/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/caliper-ai.svg)](https://pypi.org/project/caliper-ai/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-88%25-brightgreen.svg)](#development)

```bash
uvx --from caliper-ai caliper
```

That is the whole demo. Run it once against your own logs. The rest of this
document will make sense after the first table prints.

</div>

---

## The problem nobody is solving

In 2026, every paid software engineer ships code through some combination of
**Codex, Claude Code, Cursor, Copilot, Aider, Continue, Windsurf, and Cline.**
The bill that lands on the team's credit card has gone from a rounding error
to a top-five line item in eighteen months — and it is volatile every quarter
(Cursor repricing, Anthropic weekly limits, Codex rate-limit changes, vendor
"fair use" carve-outs).

Three groups of people are now asking the same question and getting different
non-answers:

- **The developer** opens five vendor dashboards, none of which reconcile to
  the others, and gives up.
- **The engineering manager** asks "what did this quarter cost us per engineer"
  and gets a finance export with the wrong taxonomy.
- **The CFO** asks "what is our AI-tools ROI" and gets a slack-thread story.

The data is already there. It is sitting in `~/.codex/sessions/`,
`~/.claude/projects/`, `~/Library/Application Support/Cursor/`, and the other
local trails every one of these tools leaves behind. It is just unjoined,
unpriced, and unread.

**Caliper is the instrument that reads all of them in one shape.**

---

## What Caliper is

A single command that:

1. **Reads** local AI coding tool trails — Codex today; Claude Code, Cursor,
   Aider, Copilot, Continue, Windsurf, Cline next.
2. **Normalizes** them into one vendor-neutral usage record per event
   (vendor, model, tier, session, project, tokens, cache, timestamp,
   provenance).
3. **Prices** them with an embedded, source-attributed rate card using
   exact Decimal math (no float drift on money).
4. **Joins** them against your local `git log` so every PR and every commit
   carries its true AI cost.
5. **Reports** them as tables, JSON, CSV, Markdown, HTML receipts, a Rich
   live TUI, a one-line statusline, forecasts with ±1σ bands, what-if
   re-pricing, budgets that exit `0/1/2` for CI, a Prometheus exporter,
   and a Grafana dashboard.
6. **Stays local.** No login. No upload. No telemetry. Anything that touches
   the network is behind an explicit `--allow-network` flag and writes only
   a local audit snapshot.

Everything above ships under **MIT, free, forever**. The local CLI is the
product. Team and enterprise tiers (post-1.0) are opt-in cloud layers that
operate on data you explicitly export — never on data Caliper is silently
collecting.

---

## Why "Datadog for AI coding spend"

Datadog won because every server's process emits metrics and somebody had to
unify them. The same shape is forming around AI coding tools today:

| Datadog (then) | Caliper (now) |
| --- | --- |
| Every server emits CPU, RAM, disk metrics in its own format. | Every AI coding tool emits a session log in its own format. |
| Ops teams can't reconcile them across cloud + on-prem + bare metal. | Dev teams can't reconcile them across Codex + Cursor + Claude Code + Copilot. |
| Vendors' own dashboards show only their own slice. | Vendors' own dashboards show only their own slice. |
| The unifying layer turned out to be observability. | The unifying layer is going to be local-first cost-and-ROI observability. |
| Won by being agent-based, cross-cloud, and unopinionated. | Win by being local-first, vendor-neutral, and Decimal-correct. |

The analogy is not "we want Datadog's margins." It is **"we are taking the
same architectural bet at the same point in the cycle."** Caliper is to AI
coding spend what early Datadog was to server metrics: the instrument
everybody installs first, before they know what they are looking for.

---

## The 90-second tour

```text
$ caliper
Caliper 0.4 • 7d / 30d / 90d • vendors: openai-codex
──────────────────────────────────────────────────────────────────────
                         7 days       30 days      90 days
──────────────────────────────────────────────────────────────────────
 events                   1,284        4,901       14,302
 input tokens             12.4 M       48.7 M      141.2 M
   cached                  8.9 M       35.1 M      102.7 M    (72%)
 output tokens             1.1 M        4.4 M       12.9 M
 reasoning tokens          0.3 M        1.3 M        3.7 M
 API-equivalent $         $48.20      $192.30      $562.10
 credits used            81,420      312,810      907,440
 top project              monorepo (61%)
 top model                gpt-5.4 standard (44%)
 pricing status           exact
 service-tier source      log: 1,109 · config: 175

 burn (last 6h)           19,300 credits/hr
 5h window                42% used · resets in 2h 11m
 weekly window            61% used · resets in 3d 04h
```

```text
$ caliper pr 1428
PR #1428  feat(billing): retry on idempotency conflict
Branch  feature/billing-retry → main          15 commits · 4 days

Vendor       Model            Events  Tokens (in/out)   Cached   Cost
─────────────────────────────────────────────────────────────────────
openai-codex gpt-5.4 standard    214   1.8 M / 0.21 M     74%   $8.10
claude-code  sonnet-4.7           39   0.34 M/ 0.06 M     58%   $0.95
cursor       composer (auto)     112   1.2 M / 0.18 M     33%   $1.40

Total                                                            $10.45
LOC shipped: +431 / -188            Cost per shipped line: $0.017
Arbitrage:  3 Opus calls on <2k-token prompts could have run on Haiku.
            Estimated waste this PR: $1.20
```

```text
$ caliper budgets check
[ok]    daily_credits      12,310 / 25,000   ( 49% )
[warn]  weekly_credits     87,420 / 100,000  ( 87% )
[ok]    monthly_credits   312,810 / 400,000  ( 78% )
exit 1   # CI-friendly: 0 ok / 1 warn / 2 breach
```

```text
$ caliper export receipt --month 2026-05 --format markdown | head
# Caliper receipt — 2026-05
Generated 2026-05-31 23:59 IST · pricing: exact

| Total                  | Value       |
| ---------------------- | ----------- |
| Events                 | 4,901       |
| Input tokens (cached)  | 35.1 M (72%)|
| API-equivalent $       | $192.30     |
| Credits (standard)     | 312,810     |
| Cache savings $        | $98.40      |
```

> Sample output. Numbers above are illustrative.
> Some commands (`caliper pr`, multi-vendor in one frame) ship on the
> roadmap below — see [What's shipping today](#whats-shipping-today) for the
> honest current state.

---

## What's shipping today

Caliper at **0.4.0** (the current release) ships:

- **OpenAI Codex CLI** — full coverage. Sessions, projects, models, tiers,
  cache reuse, rate-limit windows, burn rate, ETA-to-cap, plan metadata.
- **Vendor-neutral record format.** Every parsed event already carries a
  `vendor` field; the second parser (Claude Code) is the only thing
  required to light up cross-vendor reports.
- **All reports above** (overview, daily/weekly/monthly, session, project,
  models, tail, limits, statusline, insights, forecast, compare, whatif).
- **Receipts** (HTML, Markdown), **Prometheus exporter**, **Grafana
  dashboard**, **budgets** with CI exit codes, **doctor** / **init**.
- **Privacy by default** — local-only reads, redaction on by default.
- **Decimal math** — money never leaves Decimal until output.
- **190+ tests, 88% coverage**, Python 3.11/3.12/3.13.

Caliper at **1.0** (the milestone we are building toward) ships everything
in the [Roadmap](#roadmap) below — multi-vendor parser parity, per-PR
attribution, the editor extension, and the arbitrage advisor. Versioning is
deliberately conservative: `1.0` is reserved for the release where the CLI
surface, the vendor-neutral record, and the multi-vendor parser set are
all considered frozen.

---

## Install

Requires Python 3.11+.

```bash
# Zero-install run
uvx --from caliper-ai caliper

# Persistent install
uv tool install caliper-ai

# pipx
pipx install caliper-ai

# pip
python -m pip install caliper-ai

# With Prometheus exporter
uv tool install 'caliper-ai[prom]'

# Homebrew
brew install rajdeepmondaldotcom/tap/caliper
```

The PyPI distribution name is **`caliper-ai`**. The Python import path and
the CLI binary are both **`caliper`**. The `codex-meter` command is
preserved as a permanent alias for users upgrading from the original
release.

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

## How Caliper differs from everything adjacent

| | Vendor billing dashboards | `ccusage`, per-vendor scripts | OpenCost / FinOps for infra | **Caliper** |
| --- | :---: | :---: | :---: | :---: |
| Multi-vendor in one view | no | no | no | **yes** (roadmap) |
| Per-PR / per-commit attribution | no | partial | no | **yes** (roadmap) |
| Cache savings broken out | no | no | no | **yes** |
| Service-tier provenance | no | no | no | **yes** |
| Decimal-exact pricing math | no | no | varies | **yes** |
| Forecast + ±1σ band + ETA-to-cap | no | no | varies | **yes** |
| Budgets with CI exit codes | no | no | no | **yes** |
| Prometheus + Grafana out of the box | no | no | yes | **yes** |
| Live TUI for a tmux pane | no | no | no | **yes** |
| Works offline. Stays offline. | n/a | yes | no | **yes** |
| Local privacy by default | no | yes | n/a | **yes** |

Caliper is not trying to replace vendor billing. It is the local instrument
that sits next to it — the evidence you reach for before you escalate a
spend conversation, the receipt you reach for before you write AI off as
an expense, the dashboard you reach for before you greenlight Opus in CI.

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
- Records whether each event's model came from a JSONL `turn_context`,
  SQLite thread metadata, or a configured default. Fallback events are
  marked and priced as estimated.

### Subscription plans are metadata, not pricing magic

Caliper preserves the raw `plan_type`, adds normalized subscription plan
details for Free, Go, Plus, Pro, Business, Enterprise, Edu, Health, Gov,
and ChatGPT for Teachers, and uses the logged `codex` rate-limit bucket
for remaining-window math when multiple buckets are present. Free/Go
promotional access and Enterprise-family legacy-rate-card ambiguity
surface as warnings instead of being guessed.

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

## Privacy

Local-first is not a tagline. It is an enforced architectural posture.

- **Reports read local files only.**
- **Prompt and session labels are redacted** unless explicitly requested
  with `--show-prompts`.
- **Receipts hide full session IDs and project paths** by default. Use
  `--show-sensitive` only for private artifacts.
- **No telemetry, no analytics beacons, no auto-update phone-home.** A
  network-aware command exists, but it is named `caliper rates refresh
  --allow-network` and it only writes a local audit snapshot.
- **Exports may contain local metadata** (paths, git remotes) when those
  fields are present in source data. Treat exports as sensitive unless
  you made them to share.

Caliper aligns with the
[local-first software](https://www.inkandswitch.com/local-first/)
principles: you own your data, ownership of data lives in your hands, the
network is enhancement, not infrastructure.

---

## Roadmap

Caliper 0.4 ships full OpenAI Codex CLI coverage and the vendor-neutral
record the next milestones build on.

| Milestone | What lands |
| --- | --- |
| **0.5** | **Claude Code parser** (`~/.claude/projects/**/*.jsonl`) — same record shape, same reports, same pricing engine. First proof of vendor-neutrality. |
| **0.6** | **Cursor + Aider parsers**, cross-vendor model and tier normalization, plus a `--vendor` filter on every report. |
| **0.7** | **`caliper pr <N>`** — per-PR / per-commit attribution via local `git log` join. Every PR carries its real AI cost. The viral demo. |
| **0.8** | **Model-arbitrage advisor** — heuristic that flags spend where a cheaper model would have shipped the same work. "$X of your last week was overkill" report. |
| **0.9** | **VS Code / Cursor / Zed extension** surfacing live cost in the editor. Ambient awareness, daily active. |
| **1.0** | **Public API freeze.** Cross-vendor surface considered stable. Multi-vendor parser set (Codex + Claude Code + Cursor + Aider) ships together. |
| **1.x** | **GitHub Copilot + Continue + Windsurf + Cline parsers.** Coverage parity with the rest of the market. |
| **2.0** | **Opt-in team aggregator (paid).** Workspace rollups, Slack/Linear digests, finance export (CSV, QuickBooks, NetSuite). Local CLI stays free, MIT, offline-first. |
| **2.x** | **Enterprise tier (paid).** SSO/SAML, SOC2, on-prem aggregator, policy enforcement (model bans, daily caps), audit log. |
| **ongoing** | **AI Dev Spend Index** — opt-in anonymized cohort benchmark. "Your spend vs. P50 of $X-engineer teams." Press hook. |

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
