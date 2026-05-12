# Changelog

## Unreleased

### Refactor
- `cli.py` deduplicated: 7 commands share one set of `Annotated` option type
  aliases, dropping ~120 LOC of copy-pasted option signatures.
- `pricing.py` consolidated: `ModelCard` replaces three parallel rate dicts
  and now carries an optional `LongContextRule` per model. Long-context
  pricing is data-driven and only fires for models that declare a rule.
- `RateCard` loads the local rates file exactly once per run; aggregations
  share the same card instead of re-parsing JSON per event.
- `Usage` frozen dataclass replaces the untyped `dict[str, int]` for token
  usage everywhere — events, aggregations, and pricing all use the explicit
  shape. Reasoning output tokens are now priced at the output rate by default
  (`Rates.effective_reasoning_output`), with per-model override support.
- `humanize.py` carved out for `format_int`, `redact`, and `REDACTION_LIMIT`.
  `window_label` moved to `timeutil`.
- `limits` command now participates in the unified render pipeline and
  supports `--format table|json|csv|markdown`.
- Markdown output gained a totals row plus full Input/Cached/Output columns.
- Session-aggregate labels fall back to the session id when `--show-prompts`
  is off, so private titles never leak into redacted output.
- `gpt-5.1-codex-max` is no longer flagged as an "unknown model" just because
  it has no published API rates.
- Dead helpers `make_options`, `command_options`, `usage_kwargs`,
  `common_command_params`, and `COMMON_HELP` removed.

### Packaging
- `__version__` resolves through `importlib.metadata` with a local fallback
  so it cannot drift from `pyproject.toml`.
- `py.typed` marker shipped for PEP 561 consumers.
- `pytest-cov` wired up with coverage config; the suite currently sits at
  ~88% line+branch coverage.

## 0.1.0

- Initial open-source-ready CLI scaffold.
- Added Codex JSONL parsing, SQLite metadata joins, token aggregation, Codex credit estimates, API-equivalent dollar estimates, service-tier inference, and table/JSON/CSV/Markdown output.
