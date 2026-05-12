# codex-meter

[![CI](https://github.com/rajdeepmondaldotcom/codex-meter/actions/workflows/ci.yml/badge.svg)](https://github.com/rajdeepmondaldotcom/codex-meter/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Understand your Codex work locally.

`codex-meter` turns local Codex logs into a clear record of how your coding work
happened: sessions, projects, models, tiers, cache reuse, tokens, credits,
API-equivalent dollars, and rate-limit windows.

No cloud sync. No account login. No billing scrape. Just local evidence you can
inspect, export, and trust.

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/rajdeepmondaldotcom/codex-meter.git
cd codex-meter
uv tool install .
codex-meter
```

With `pipx`:

```bash
pipx install .
codex-meter
```

Prometheus exporter:

```bash
uv tool install '.[prom]'
```

## Start Here

```bash
codex-meter                         # 7 / 30 / 90 day overview
codex-meter doctor                  # check local data and assumptions
codex-meter live                    # watch usage while you work
codex-meter project --days 30       # see project activity
codex-meter models --days 30        # inspect model and tier mix
```

The first run parses local session files. Later runs use a sidecar parse cache.
Use `--no-parse-cache` when debugging parser behavior.

## Why It Exists

Codex already leaves a detailed trail on your machine. The problem is that the
trail is split across JSONL sessions, SQLite metadata, config, rate-limit
samples, and pricing assumptions. `codex-meter` turns that trail into one local
view.

It answers:

- What did I use?
- Where did it go?
- Which model and tier drove it?
- How much input was cached?
- What changed across sessions, projects, and days?

This is not an OpenAI billing ledger. It is local usage intelligence.

## Commands

| Need | Command |
| --- | --- |
| Overview | `codex-meter` |
| Daily / weekly / monthly | `codex-meter daily`, `weekly`, `monthly` |
| Sessions | `codex-meter session --top 20` |
| Projects | `codex-meter project --days 30` |
| Models and tiers | `codex-meter models --days 30` |
| Recent events | `codex-meter tail --n 20` |
| Rate limits | `codex-meter limits` |
| Insights | `codex-meter insights` |
| Forecast | `codex-meter forecast --days 14` |
| Compare windows | `codex-meter compare --a "last 7 days" --b "previous 7 days"` |
| What-if pricing | `codex-meter whatif --tier standard` |
| Optional budgets | `codex-meter budgets check` |
| Receipt | `codex-meter export receipt --month 2026-05 --format html` |
| Prometheus | `codex-meter export prometheus --port 9090` |
| Grafana | `codex-meter export grafana > dashboard.json` |

Most report commands support:

```bash
--format table|json|csv|markdown
--output report.json
--since 2026-05-01
--days 30
--top 20
```

## Live View

```bash
codex-meter live
```

Shows today's usage, trailing 7-day usage, 5-hour and weekly windows, burn rate,
and ETA to 100% when enough samples exist.

Hotkeys:

| Key | Action |
| --- | --- |
| `q` | Quit |
| `?` | Help |
| `r` | Refresh |
| `p` | Pause |

## Budgets

Create a config:

```bash
codex-meter init
```

Add limits:

```toml
[budgets]
daily_credits = 25000
weekly_credits = 100000
monthly_credits = 400000
weekly_api_dollars = 50.0
```

Check them:

```bash
codex-meter budgets check
```

Exit codes are built for automation:

| Exit | Meaning |
| ---: | --- |
| `0` | ok |
| `1` | warning |
| `2` | breached or failed |

## Exports

```bash
codex-meter export receipt --month 2026-05 --format markdown
codex-meter export receipt --month 2026-05 --format html > receipt.html
codex-meter export prometheus --host 127.0.0.1 --port 9090
codex-meter export grafana > dashboard.json
```

Receipts redact local session and project labels by default. Use
`--show-sensitive` only for private artifacts.

Prometheus exposes credits, burn rate, rate-limit window percent, event count,
long-context event count, and tokens by model/tier/kind.

## Data Sources

`codex-meter` reads:

- `~/.codex/sessions/**/*.jsonl`
- `~/.codex/state_5.sqlite`
- `~/.codex/config.toml`

Normal reports do not touch the network. The only networked command is explicit:

```bash
codex-meter rates refresh --allow-network
```

That writes a local pricing-source audit snapshot. It does not rewrite the
embedded rate card.

## Accuracy

The hard part is not adding tokens. It is making assumptions visible.

`codex-meter` tracks cached input separately, prices reasoning output, applies
per-model long-context rules, warns on fallback-priced models, and reports
whether service tiers came from logs, config, overrides, or assumptions.

Service-tier precedence:

1. `--service-tier standard|fast`
2. `--tier-overrides overrides.json`
3. logged tier
4. current `~/.codex/config.toml`
5. `--unknown-service-tier`

Inspect pricing:

```bash
codex-meter rates show
codex-meter rates show --format json
```

Use local overrides when needed:

```bash
codex-meter daily --rates-file ./rates.json
```

Schemas:

- [`schemas/rates.schema.json`](schemas/rates.schema.json)
- [`schemas/tier-overrides.schema.json`](schemas/tier-overrides.schema.json)

## Privacy

The default posture is local and conservative.

- Reports read local files.
- Prompt and session labels are redacted unless requested.
- Receipts hide full session IDs and project paths by default.
- JSON, CSV, Markdown, and HTML exports may still contain local metadata.

Treat exports as sensitive unless you made them for sharing.

## Development

```bash
uv sync --dev
uv run ruff check .
uv run ruff format --check .
PYTHONWARNINGS=error::ResourceWarning uv run pytest
uv run pytest --cov=src/codex_meter --cov-report=term
uv run python -m build
```

Smoke test against your own logs:

```bash
uv run codex-meter doctor
uv run codex-meter overview
uv run codex-meter rates show
```

## License

MIT
