# Changelog

## 1.0.0

### Added
- **Live TUI** (`codex-meter live`): full-window dashboard with today's credits, 7-day
  total, 5-hour primary + weekly secondary countdowns, burn rate, ETA to 100%.
  Border turns red at >= 80% used. `--interval` to tune refresh, graceful SIGINT.
- **Window math** (`windows.py`): `WindowState` decoded from rate-limit samples;
  Unix-epoch `resets_at` handled correctly; burn rate requires >= 3 samples in
  a 6-hour lookback; ETA projection only when burn rate is positive.
- **Analytics suite**:
  - `forecast`: month-end credit projection with linear + EWMA estimators
    and a ±1σ band. Optional `--cap` reports days-to-depletion.
  - `compare --a --b`: side-by-side credit, dollar, and token deltas
    between two windows (`last 7 days`, `previous 7 days`, ISO ranges, etc.).
  - `whatif --tier --model`: re-cost the trailing window under a hypothetical
    tier or model swap; rejects unknown models with the rate-card list.
- **Budgets** (`budgets check`): TOML `[budgets]` table (flat keys,
  nested-by-period, or `items = [...]` list). Severity ladder ok/warn/breach
  drives the exit code so CI can gate on it.
- **Rate card subcommands**:
  - `rates show` (table + JSON) with age + stale-after-90d flag.
  - `rates refresh` stub reserved for the network-opt-in flow.
- **Exporters**:
  - `export grafana`: dashboard JSON wired to codex-meter Prometheus metrics.
  - `export receipt --month YYYY-MM --format markdown|html`: totals, models,
    top sessions, top projects. HTML escapes user-supplied labels.
  - `export prometheus --host --port`: stdlib `/metrics` endpoint serving
    `codex_meter_credits_used`, `burn_per_hour`,
    `window_used_percent{window}`, `tokens_total{model,tier,kind}`,
    `events_total`, `long_context_events_total`. Binds 127.0.0.1 by default.
  - `[prom]` optional extra installs `prometheus-client`.
- **`init`** subcommand: scaffolds `.codex-meter.toml` with commented defaults;
  refuses overwrite without `--force`.
- **`doctor` v2**: Python version, session root + file count, state DB, Codex
  config, `codex --version` (best-effort), rate-card age, clock skew vs latest
  event, parser warnings. JSON output for CI. Exit code reflects worst check.
- **Intervals** (`intervals.py`): `today`, `yesterday`, `last N days`,
  `previous N days`, `last N hours`, `this/last week`, `this/last month`,
  ISO date, `YYYY-MM-DD..YYYY-MM-DD` range.
- **JSON Schemas**: `schemas/rates.schema.json`, `schemas/tier-overrides.schema.json`
  (Draft 2020-12) for editor autocomplete + validation.

### Pricing accuracy
- `Rates` gains `reasoning_output` (defaults to `output` rate). Pricing now
  accounts for reasoning tokens, which were previously invisible.
- `LongContextRule` lives on `ModelCard`; only `gpt-5.5` carries the
  272K-token, ×2/×1.5 rule today. Other models do not get the multiplier.

### Refactor
- `cli.py` deduplicated: subcommands share `Annotated` Option type aliases.
- `ModelCard` replaces parallel rate dicts.
- `RateCard` loads any local override file exactly once per run.
- `Usage` frozen dataclass replaces ad-hoc `dict[str, int]` usage shapes
  across events, aggregation, and pricing.
- `humanize.py` carved out for `format_int`, `redact`, `REDACTION_LIMIT`.
- `limits` command participates in the unified render pipeline and
  supports `--format table|json|csv|markdown` with decoded reset times.

### Packaging
- `__version__` resolves through `importlib.metadata` with a local fallback.
- `py.typed` marker shipped (PEP 561).
- `pytest-cov` wired up; line+branch coverage at >= 82%.

## 0.1.0

- Initial open-source-ready CLI scaffold.
- Added Codex JSONL parsing, SQLite metadata joins, token aggregation, Codex
  credit estimates, API-equivalent dollar estimates, service-tier inference,
  and table/JSON/CSV/Markdown output.
