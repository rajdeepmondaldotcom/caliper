# codex-meter

`codex-meter` is an offline-first CLI for understanding local OpenAI Codex usage. It reads your local Codex session JSONL files and state database, then reports tokens, cached input, output, reasoning output, estimated Codex credits, API-equivalent dollars, sessions, projects, models, and recent rate-limit samples.

It is designed to feel familiar if you use `ccusage`, but it is Codex-specific: service-tier inference, Codex credit estimates, privacy-safe session labels, project/cwd grouping, and multi-window summaries are first-class.

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

Published package install, once released:

```bash
pipx install codex-meter
```

## Quick Start

```bash
codex-meter
codex-meter daily --days 7
codex-meter monthly --since 2026-05-01 --format json
codex-meter session --days 30 --show-prompts
codex-meter project --days 90
codex-meter limits
codex-meter doctor
```

By default, `codex-meter` reports rolling 7, 30, and 90 day usage using local logs under `~/.codex/sessions`.

## Commands

- `codex-meter` / `codex-meter overview`: rolling 7/30/90 day summary.
- `codex-meter daily`: usage grouped by date.
- `codex-meter weekly`: usage grouped by ISO week.
- `codex-meter monthly`: usage grouped by month.
- `codex-meter session`: usage grouped by local Codex session.
- `codex-meter project`: usage grouped by project/cwd from Codex metadata.
- `codex-meter models`: usage grouped by model and service tier.
- `codex-meter limits`: recent rate-limit samples found in token events.
- `codex-meter doctor`: local path and data availability checks.

Supported output formats:

```bash
--format table
--format json
--format csv
--format markdown
```

## Data Sources

`codex-meter` reads:

- `~/.codex/sessions/**/*.jsonl` for token count events.
- `~/.codex/state_5.sqlite` for session metadata such as title, cwd, git branch, model, and reasoning effort.
- `~/.codex/config.toml` for current service-tier fallback when historical logs do not record the tier.

No network access is required for reports. Pricing data is embedded and can be overridden locally.

## Pricing And Credits

The bundled rate card was checked on 2026-05-12 against:

- OpenAI API Pricing: https://openai.com/api/pricing/
- GPT-5.5 model pricing and long-context rule: https://developers.openai.com/api/docs/models/gpt-5.5
- Codex rate card: https://help.openai.com/en/articles/20001106-codex-rate-card

The dollar value is an API-equivalent estimate from local logs. It is not an OpenAI billing ledger, especially when Codex usage is included in a ChatGPT plan.

Use a local rates file when the published rate card changes:

```json
{
  "api": {
    "gpt-5.5": { "input": 5, "cached_input": 0.5, "output": 30 }
  },
  "credits": {
    "gpt-5.5": { "input": 125, "cached_input": 12.5, "output": 750 }
  }
}
```

```bash
codex-meter daily --rates-file ./rates.json
```

## Service Tier Accuracy

Codex historical logs may not always record whether a request used standard or fast mode. `codex-meter` uses this precedence:

1. `--service-tier standard|fast`
2. `--tier-overrides overrides.json`
3. Logged tier in session events
4. Current `~/.codex/config.toml`
5. `--unknown-service-tier`

Tier override example:

```json
{
  "overrides": [
    {
      "start": "2026-05-12 09:00:00",
      "end": "2026-05-12 13:30:00",
      "service_tier": "standard"
    },
    {
      "session": "rollout-2026-05-12T18-36-01-example.jsonl",
      "service_tier": "fast"
    }
  ]
}
```

## Privacy

Human-readable output redacts long prompt/session text by default. Use `--show-prompts` when you want full local details. JSON output includes structured metadata and should be treated as potentially sensitive if shared.

## Development

```bash
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python -m build
```

Local smoke test:

```bash
uv run codex-meter doctor
uv run codex-meter daily --days 1 --format json
```

## License

MIT
