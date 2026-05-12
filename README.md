# codex-meter

[![CI](https://github.com/rajdeepmondaldotcom/codex-meter/actions/workflows/ci.yml/badge.svg)](https://github.com/rajdeepmondaldotcom/codex-meter/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

OpenAI Codex writes usage data to your machine. `codex-meter` turns that local
trail into numbers you can check before you act.

It answers the questions that matter after a real coding session:

- How many tokens did I use?
- How much was cached input?
- Which projects, sessions, models, and service tiers did the work?
- What did that usage mean in Codex credits and API-equivalent dollars?
- Am I getting close to a rate-limit window or budget I care about?

It is not an OpenAI billing ledger. It is local accounting from local evidence.

## Install

Requires Python 3.11 or newer.

From a checkout:

```bash
git clone https://github.com/rajdeepmondaldotcom/codex-meter.git
cd codex-meter
uv tool install .
codex-meter doctor
codex-meter
```

With `pipx` from a checkout:

```bash
pipx install .
codex-meter
```

For the Prometheus exporter:

```bash
uv tool install '.[prom]'
```

## First Run

```bash
codex-meter                         # rolling 7 / 30 / 90 day overview
codex-meter doctor                  # check paths, parser health, rate-card age
codex-meter live                    # live terminal dashboard
codex-meter project --days 30       # usage by project / cwd
codex-meter models --days 30        # usage by model and service tier
```

The first run parses your local Codex session files. Later runs use a sidecar
parse cache unless you pass `--no-parse-cache`.

## What It Reads

`codex-meter` reads local Codex files:

- `~/.codex/sessions/**/*.jsonl` for token-count and turn-context events.
- `~/.codex/state_5.sqlite` for titles, cwd, branches, model names, and reasoning settings.
- `~/.codex/config.toml` for fallback service-tier information when older logs do not say.

Normal reports do not send your logs anywhere. The only networked command is
explicit: `codex-meter rates refresh --allow-network`, which fetches pricing
source pages into a local audit snapshot.

## What You Get

| Job | Command |
| --- | --- |
| See rolling usage | `codex-meter` or `codex-meter overview` |
| Group by day, week, or month | `codex-meter daily`, `codex-meter weekly`, `codex-meter monthly` |
| Find expensive sessions | `codex-meter session --days 30 --top 20` |
| Find expensive projects | `codex-meter project --days 30 --top 20` |
| Check model and tier mix | `codex-meter models --days 30` |
| Watch current usage | `codex-meter live` |
| Inspect rate-limit samples | `codex-meter limits` |
| Forecast month-end usage | `codex-meter forecast --days 14` |
| Compare two windows | `codex-meter compare --a "last 7 days" --b "previous 7 days"` |
| Re-cost a scenario | `codex-meter whatif --tier standard` |
| Gate on budgets | `codex-meter budgets check` |
| Export a receipt | `codex-meter export receipt --month 2026-05 --format html` |
| Export Prometheus metrics | `codex-meter export prometheus --port 9090` |
| Emit a Grafana dashboard | `codex-meter export grafana > dashboard.json` |

Most report commands support `--format table|json|csv|markdown` and `--output`.
Receipts keep their own formats: markdown and HTML.

## The Core Reports

Use the grouped reports when you want to know where the usage went:

```bash
codex-meter daily --days 7
codex-meter weekly --since 2026-05-01
codex-meter monthly --format markdown
codex-meter session --days 30 --top 20
codex-meter project --days 30 --top 20
codex-meter models --days 30 --format json
```

Use the investigation commands when a number looks wrong or a session needs a
closer look:

```bash
codex-meter tail --n 20
codex-meter tail --by session --n 10
codex-meter limits --days 7
codex-meter insights --format markdown
codex-meter doctor --format json
```

Use the planning commands when you need a decision, not just a report:

```bash
codex-meter forecast --days 14 --cap 500000
codex-meter compare --a "last 7 days" --b "previous 7 days"
codex-meter whatif --days 7 --tier fast
codex-meter whatif --days 7 --model gpt-5.4-mini
codex-meter budgets check
```

## Live Dashboard

`codex-meter live` gives you a terminal dashboard for active work:

- today's usage
- trailing 7-day usage
- primary 5-hour and secondary weekly windows
- burn rate
- ETA to 100 percent when enough samples exist

Hotkeys:

| Key | Action |
| --- | --- |
| `q` | Quit |
| `?` | Toggle help |
| `r` | Refresh now |
| `p` | Pause or resume auto-refresh |

## Budgets

Run `codex-meter init` to scaffold `.codex-meter.toml`.

A small budget config looks like this:

```toml
[budgets]
daily_credits = 25000
weekly_credits = 100000
monthly_credits = 400000
weekly_api_dollars = 50.0
```

Then gate a shell script or CI job:

```bash
codex-meter budgets check
```

Exit codes are intentional:

| Exit | Meaning |
| ---: | --- |
| `0` | ok |
| `1` | warning threshold crossed |
| `2` | budget breached or check failed |

Nested budgets can set their own warning threshold:

```toml
[budgets.monthly]
credits = 500000
warn_at = 0.7
```

## Exports

```bash
codex-meter export receipt --month 2026-05 --format markdown
codex-meter export receipt --month 2026-05 --format html > receipt.html
codex-meter export prometheus --host 127.0.0.1 --port 9090
codex-meter export grafana > dashboard.json
```

Receipts redact full local labels by default. Use `--show-sensitive` only for
private artifacts.

Prometheus exposes `/metrics` with gauges for credits, burn rate, rate-limit
window percent, event count, long-context event count, and tokens by
model/tier/kind.

## Accuracy Model

The hard part is not adding up tokens. The hard part is knowing which assumptions
were used.

`codex-meter` keeps those assumptions visible:

- Reasoning output is priced separately and defaults to the output rate when a card does not specify it.
- Cached input is tracked separately from uncached input.
- Long-context rules live on the model card, not in ad hoc report code.
- Fallback-priced models are surfaced as fallback-priced instead of being quietly normalized.
- Rate-card age is shown by `codex-meter rates show` and checked by `codex-meter doctor`.

For service tier, historical Codex logs may not always say whether a request was
`standard` or `fast`. The resolution order is:

1. `--service-tier standard|fast`
2. `--tier-overrides overrides.json`
3. logged tier on the event
4. current `~/.codex/config.toml`
5. `--unknown-service-tier`

Override schemas are included for editor validation:

- [`schemas/rates.schema.json`](schemas/rates.schema.json)
- [`schemas/tier-overrides.schema.json`](schemas/tier-overrides.schema.json)

Inspect the embedded card:

```bash
codex-meter rates show
codex-meter rates show --format json
```

Use a local rates file when you need to pin your own numbers:

```bash
codex-meter daily --rates-file ./rates.json
```

## Pricing Sources

The embedded rate card declares the source dates it was checked against. The
bundled card currently records source checks dated 2026-05-12 against:

- OpenAI API pricing: <https://openai.com/api/pricing/>
- GPT-5.5 model docs: <https://developers.openai.com/api/docs/models/gpt-5.5>
- GPT-5.1-Codex-Max model docs: <https://developers.openai.com/api/docs/models/gpt-5.1-codex-max>
- Codex rate card: <https://help.openai.com/en/articles/20001106-codex-rate-card>

If the card gets old, `doctor` tells you. If you need a local audit snapshot:

```bash
codex-meter rates refresh --allow-network
```

That command writes fetched source evidence locally. It does not rewrite the
embedded card.

## Privacy

The default posture is local and conservative.

- Reports read local Codex files.
- Prompt and session labels are redacted in human-readable output unless you ask for more detail.
- Receipts hide full session IDs and local project paths by default.
- JSON output is structured and useful, but it may still contain local metadata.

Treat exported JSON, CSV, Markdown, and HTML as potentially sensitive when
sharing them.

## Configuration

`codex-meter init` creates a commented config:

```bash
codex-meter init
```

Config is read from:

1. `~/.config/codex-meter/config.toml`
2. `.codex-meter.toml`
3. the path passed with `--config`

CLI flags override config defaults for that invocation.

Useful defaults:

```toml
default_days = 30
timezone = "local"
service_tier = "auto"
unknown_service_tier = "current-config"
default_model = "gpt-5.5"
top_threads = 10
```

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
