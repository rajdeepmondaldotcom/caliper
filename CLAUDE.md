# CLAUDE.md — codex-meter project guide

Offline-first CLI that turns local OpenAI Codex session logs into usage reports,
forecasts, budgets, live TUIs, and integration exports. Read this before
making changes.

## Project shape

- Python 3.11+, packaged with `hatchling`, managed with `uv`.
- Entry point: `codex-meter = "codex_meter.cli:app"` (Typer).
- Library code under `src/codex_meter/`, tests under `tests/`.
- No network calls in the default path. Optional `[prom]` extra adds
  `prometheus-client`. Anything that talks to the network must gate behind an
  explicit flag and document the implication.

## Top-level commands

`overview` (default) · `daily` · `weekly` · `monthly` · `session` · `project` ·
`models` · `limits` · `insights` · `tail` · `live` · `forecast` · `compare` · `whatif` ·
`rates show|refresh` · `budgets check` · `export prometheus|grafana|receipt` ·
`doctor` · `init`

Every grouped command supports `--format table|json|csv|markdown`.

## Module map

| Module | Purpose |
| --- | --- |
| `cli.py` | Typer command surface + the `Annotated[...]` option aliases. Bodies stay thin — most logic lives elsewhere. |
| `config.py` | TOML config layering (`USER_CONFIG`, `LOCAL_CONFIG`, explicit `--config`) → `RuntimeOptions`. Validates `pricing_mode`, `service_tier`, `unknown_service_tier`. |
| `parser.py` | JSONL streaming + SQLite (`state_5.sqlite`) join. Emits `LoadResult` (events + duplicates + tier_sources + rate-limit samples + warnings). |
| `models.py` | All dataclasses. `Usage` is **frozen**; `Rates` has `effective_reasoning_output`; `ModelCard` may carry a `LongContextRule`. |
| `pricing.py` | Embedded rate card + `RateCard.cost_for(usage, model, tier)`. Long-context rule is per-model. |
| `insights.py` | Pure insight heuristics for cache savings, tier confidence, spend concentration, and trend acceleration. |
| `parse_cache.py` | Sidecar SQLite cache for parsed JSONL sessions, keyed by file stat + parser signature independent of report windows. |
| `aggregation.py` | Daily/weekly/monthly/session/project/model+tier rollups. Accepts an optional pre-built `RateCard` to avoid re-parsing per call. |
| `render.py` | Output formatters (table/json/csv/markdown) including the limits decoder. |
| `windows.py` | Pure functions over rate-limit samples: `WindowState`, burn rate (3+ samples, 6h lookback), ETA-to-100, epoch decode. |
| `live.py` | Rich `Live` + `Layout` TUI. `collect_frame()` builds a snapshot; `render_frame()` draws three panels. |
| `forecasts.py` | Linear + EWMA projection, ±1σ band, optional days-to-cap. |
| `intervals.py` | Natural-language window parser (`last 7 days`, `previous 7 days`, `this/last week`, `this/last month`, ISO ranges). |
| `budgets.py` | `Budget` + `BudgetAlert` + `evaluate` + `parse_budgets_table` (three input shapes). |
| `exporters.py` | Markdown/HTML receipts + Grafana dashboard JSON. |
| `prom_export.py` | Optional Prometheus exporter. Imports `prometheus_client` at module load → triggers a friendly install hint if absent. |
| `timeutil.py` | `parse_datetime`, `iso_z`, day/week/month keys, `window_label`. |
| `humanize.py` | `format_int`, `redact`, `REDACTION_LIMIT`. |

## Invariants to preserve

1. **Offline by default.** Adding network calls requires a flag, a clear
   warning, and tests that exercise the offline path unchanged.
2. **Frozen dataclasses for value objects.** `Usage`, `Rates`, `ThreadMeta`,
   `UsageEvent`, `RateLimitSample`, `LoadResult`, `RuntimeOptions`,
   `LongContextRule`, `ModelCard`, `BudgetAlert`, `Interval`, `WindowState`,
   `LiveFrame`, `ReceiptInputs`, `Projection`. Don't switch to mutable
   variants without a hard reason.
3. **Reasoning tokens cost output rate.** `Rates.effective_reasoning_output`
   falls back to `output`; the per-model rate card may override. Any new
   pricing code must apply the long-context input/output multipliers when
   `ModelCard.long_context` matches the input-token threshold.
4. **Service-tier precedence chain:** CLI override → `--tier-overrides` JSON
   → logged tier → current `~/.codex/config.toml` → assumed standard. Each
   event records which source resolved its tier so doctor + JSON output can
   surface the source counts.
5. **Privacy by default.** `--show-prompts` is the only path that lets long
   prompts/titles leave the redaction limit. Session-aggregate labels fall
   back to `session_id` (not title/first message) when redaction is on, so
   JSON output never leaks names.
6. **Severity-driven exit codes.** `budgets check` and `doctor` exit
   0 (ok) / 1 (warn) / 2 (fail|breach). CI gating depends on this.
7. **Frozen rate-card timestamp.** `PRICING_SOURCES[*].checked` is the source
   of truth for "rate card age." `doctor` warns >30 days, fails >90 days.

## Workflow

```bash
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest                                # 140+ tests
uv run pytest --cov=src/codex_meter          # coverage report
uv run python -m build                       # build sdist + wheel
```

CI workflow at `.github/workflows/ci.yml` matrixes Python 3.11/3.12/3.13.

## Adding a subcommand

1. Define new `Annotated[...]` typer Option aliases at the top of `cli.py`
   only if no existing alias fits.
2. Add the command body. Keep it thin — push logic into a new pure module
   when possible (see `windows.py`, `forecasts.py`, `budgets.py`).
3. Friendly errors via `raise _exit_error("message")` (exits with code 2 and
   prints `[red]error:[/red] message`).
4. Add tests:
   - Unit tests for the pure module (parametrize-heavy).
   - CLI smoke test via `typer.testing.CliRunner` (happy path + at least one
     error path + JSON format if applicable).
5. Run `uv run ruff check --fix . && uv run ruff format .` before committing.

## Test conventions

- `tests/conftest.py` provides `write_session()`, `token_event()`,
  `turn_context()`, `make_state_db()` fixtures.
- For CLI tests, build a fixture session + state DB, then invoke through
  `CliRunner`. Pass `--codex-config <missing-path>` so the test doesn't
  pick up the developer's real `~/.codex/config.toml`.
- TUI/Console snapshot tests pin `Console(record=True, width=140,
  color_system=None)` and assert against `export_text()` substrings.
- Don't mock the database in integration tests; use a real sqlite via the
  conftest helpers.

## Rate-card maintenance

When OpenAI updates published pricing:

1. Edit `MODEL_CARDS` in `src/codex_meter/pricing.py` (or add a new card).
2. Update every `PRICING_SOURCES[*].checked` to today's ISO date.
3. Update `## Pricing` in `README.md` to match.
4. Re-run `uv run pytest`. If pricing assertions drift, fix the assertions
   only after manually re-computing the expected values from the docstring
   formula in `test_pricing.py`.

## Common pitfalls

- **Don't write to `~/.codex/state_5.sqlite`.** Codex CLI owns it. Open it
  read-only.
- **Don't reintroduce `dict[str, int]` for usage.** Use the `Usage`
  dataclass; mutate by constructing a new instance.
- **Don't compute pricing inside aggregation hot loops without passing the
  pre-built `RateCard`.** Per-event `RateCard.load(...)` blows up JSON
  parsing N times.
- **Don't mix stdout + stderr in JSON paths.** Errors go through
  `_exit_error` which prints to stdout via Rich today — fine for tests but
  beware of pipelines.
- **Don't add files inside `~/.codex/`.** Cache directories live under
  `platformdirs.user_cache_dir("codex-meter")` (only added if/when the
  parse cache phase ships).

## Deferred work

- **Coverage to 85%+** — currently ~82%. Big gaps: `live.run_live`,
  `prom_export.serve_forever`, several CLI command bodies. Likely needs
  mocked HTTP server + `max_ticks` plumbed through.
- **`rates refresh` network path** — opt-in audit snapshot exists; automatic
  embedded-card updates are intentionally still manual.
- **PyPI Trusted Publisher CI + Homebrew tap** — needs maintainer OIDC setup.

## Tone for commits and PRs

Conventional commits-style: `feat:` / `fix:` / `refactor:` / `test:` /
`docs:` / `chore:`. PR titles under 70 chars; body details. Always note
which phase the change extends (e.g. `feat(phase 6): …`).
