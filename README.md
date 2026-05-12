# codex-meter

`codex-meter` is an **offline-first CLI** for understanding local OpenAI Codex usage.
It reads your local Codex session logs + state DB and reports tokens, cached input,
output, reasoning output, estimated Codex credits, API-equivalent dollars, sessions,
projects, models, and rate-limit windows — all without a single network call.

Think `ccusage`, but Codex-specific: service-tier inference, Codex credit estimates,
privacy-safe session labels, project/cwd grouping, a live TUI, forecasts, what-ifs,
budgets with CI-gateable exit codes, and a Prometheus exporter.

## Highlights

- **Rolling 7/30/90 day overview** out of the box.
- **`codex-meter live`** — full-window TUI: burn rate, 5-hour primary + weekly
  secondary countdowns, ETA-to-100% projection.
- **`codex-meter forecast` / `compare` / `whatif`** — month-end projection with a
  ±1σ band, A vs B window diff, tier/model swap re-cost.
- **`codex-meter budgets check`** — TOML-defined budgets with severity-driven
  exit codes (0 ok / 1 warn / 2 breach) for CI gating.
- **`codex-meter export`** — Prometheus `/metrics`, Grafana dashboard JSON,
  monthly receipt (markdown or HTML).
- **`codex-meter doctor`** — Python version, paths, Codex CLI, rate-card age,
  clock skew, parser warnings; JSON + non-zero exit for CI.
- **Reasoning tokens priced correctly** (defaults to the output rate); per-model
  long-context rules; embedded rate card + override via `--rates-file`.

## Install

From a checkout:

```bash
uv tool install .
codex-meter
```

Or with `pipx`:

```bash
pipx install .
codex-meter
```

Optional integrations:

```bash
pipx install 'codex-meter[prom]'   # adds prometheus_client
```

## Quick start

```bash
codex-meter                            # rolling 7/30/90 day overview
codex-meter daily --days 7             # per-day breakdown
codex-meter live                       # full-window TUI dashboard
codex-meter forecast --days 14         # month-end projection
codex-meter compare --a "last 7 days" --b "previous 7 days"
codex-meter whatif --tier standard     # re-cost the last 7 days as if standard
codex-meter budgets check              # CI-gateable severity exit codes
codex-meter rates show                 # active rate card + age
codex-meter doctor                     # health check
codex-meter init                       # scaffold .codex-meter.toml
```

Every report supports `--format table|json|csv|markdown`.

## Commands

| Command | Description |
| --- | --- |
| `overview` | Rolling 7 / 30 / 90 day summary (default). |
| `daily` | Usage grouped by date. |
| `weekly` | Usage grouped by ISO week. |
| `monthly` | Usage grouped by month. |
| `session` | Usage grouped by Codex session. |
| `project` | Usage grouped by project / cwd. |
| `models` | Usage grouped by model and service tier. |
| `limits` | Decoded rate-limit windows + recent samples. |
| `live` | Refresh-1Hz TUI with burn rate, 5h + weekly countdowns. |
| `forecast` | Month-end projection ± 1σ band + days-to-depletion. |
| `compare` | Diff two windows (`last 7 days`, ISO ranges, etc.). |
| `whatif` | Re-cost the window under a hypothetical tier/model swap. |
| `budgets check` | TOML budgets → ok / warn / breach exit codes. |
| `rates show` / `refresh` | Inspect or (planned) refresh the embedded rate card. |
| `export prometheus` | Serve `/metrics` (default 127.0.0.1:9090). |
| `export grafana` | Emit a Grafana dashboard JSON. |
| `export receipt` | Monthly receipt (markdown or HTML). |
| `doctor` | Health check; exit code = worst severity. |
| `init` | Scaffold `.codex-meter.toml`. |

## Data sources

`codex-meter` reads only local files:

- `~/.codex/sessions/**/*.jsonl` — token-count + turn-context events.
- `~/.codex/state_5.sqlite` — title, cwd, git branch, model, reasoning effort.
- `~/.codex/config.toml` — fallback service tier when logs don't record one.

No network calls. Pricing is embedded and overridable via `--rates-file`.

## Pricing

The bundled rate card was checked **2026-05-12** against:

- OpenAI API pricing — https://openai.com/api/pricing/
- GPT-5.5 model + long-context rule — https://developers.openai.com/api/docs/models/gpt-5.5
- Codex rate card — https://help.openai.com/en/articles/20001106-codex-rate-card

Run `codex-meter rates show` to inspect the active card + its age. The card
declares its source dates; `codex-meter doctor` warns when they exceed 30 days
and fails when they exceed 90.

**Dollar values are API-equivalent estimates from local logs.** They are not an
OpenAI billing ledger — especially when Codex usage is rolled into a ChatGPT
plan. Codex credits are the right unit for plan-side reasoning.

Local overrides (per [`schemas/rates.schema.json`](schemas/rates.schema.json)):

```json
{
  "api": {
    "gpt-5.5": { "input": 5, "cached_input": 0.5, "output": 30, "reasoning_output": 30 }
  },
  "credits": {
    "gpt-5.5": { "input": 125, "cached_input": 12.5, "output": 750 }
  }
}
```

```bash
codex-meter daily --rates-file ./rates.json
```

## Service tier accuracy

Codex historical logs may not record whether a request used standard or fast.
`codex-meter` resolves the tier via this precedence:

1. `--service-tier standard|fast` — uniform CLI override.
2. `--tier-overrides overrides.json` — per-session or per-window assertions
   (schema: [`schemas/tier-overrides.schema.json`](schemas/tier-overrides.schema.json)).
3. Logged tier on the event payload.
4. Current `~/.codex/config.toml` tier setting.
5. `--unknown-service-tier` fallback.

## Budgets

Add a `[budgets]` table to `.codex-meter.toml` (run `codex-meter init` to scaffold):

```toml
[budgets]
daily_credits = 25000
weekly_credits = 100000
weekly_api_dollars = 50.0

# Or nested with a per-period warn threshold:
# [budgets.monthly]
# credits = 500000
# warn_at = 0.7
```

```bash
codex-meter budgets check         # exits 0/1/2 by severity
codex-meter budgets check --format json | jq
```

## Live + integrations

```bash
codex-meter live                                # TUI
codex-meter export prometheus --port 9090       # /metrics on 127.0.0.1
codex-meter export grafana > dashboard.json     # Grafana JSON
codex-meter export receipt --month 2026-05 --format html > receipt.html
```

## Privacy

Human-readable output redacts long prompt/session text by default. Use
`--show-prompts` for full local details. JSON output includes structured
metadata; treat it as potentially sensitive when sharing.

## Development

```bash
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest                   # 130+ tests
uv run pytest --cov=src/codex_meter --cov-report=term
uv run python -m build
```

Smoke test against your own logs:

```bash
uv run codex-meter doctor
uv run codex-meter overview
```

## License

MIT
