# Phase 2 - Self-Audit

## Audit Method

Compared the Phase 1 plan against these implementation surfaces:

- `src/codex_meter/models.py`
- `src/codex_meter/parser.py`
- `src/codex_meter/parse_cache.py`
- `src/codex_meter/aggregation.py`
- `src/codex_meter/render.py`
- `src/codex_meter/live.py`
- `src/codex_meter/cli.py`
- `tests/test_parser.py`
- `tests/test_aggregation.py`
- `tests/test_formats.py`
- `tests/test_parse_cache.py`
- `tests/test_live.py`

## Findings

### Finding 1 - External Codex parity is mostly already satisfied

The referenced Codex package exposes daily, monthly, and session reports with
JSON, compact output, timezone/date filtering, cached-token accounting, and
offline pricing. `codex-meter` already covers those and adds weekly, project,
models, limits, insights, tail, forecast, compare, what-if, budgets, live,
receipts, Prometheus, and Grafana.

Implementation should therefore focus on depth and explainability, not command
count.

### Finding 2 - Project aggregation is too shallow

`aggregate_projects()` groups by `ThreadMeta.cwd`, but `Aggregate` only retains
totals, models, tiers, plan types, usage sources, and pricing flags. Once rows
reach `render.py`, the command cannot explain sessions, project names, git refs,
or first/last activity. This blocks richer JSON insights.

### Finding 3 - Parser already has the right context hook

`update_context_from_event()` already reads `turn_context` for model, effort,
and service tier. Adding `cwd` handling there is the lowest-risk way to support
workspace fallback when `state_5.sqlite` is missing.

### Finding 4 - State DB loading is schema-tolerant

`load_thread_metadata()` dynamically checks available columns. New optional
metadata fields can be added without breaking older state DB schemas.

### Finding 5 - Parse-cache decode is too strict

`_thread_from_dict()` currently calls `ThreadMeta(**raw)`. It handles missing
new fields because dataclass defaults exist, but fails on future extra keys.
The plan must filter decoded keys to known dataclass fields.

### Finding 6 - JSON schema tests are pinned

`tests/test_formats.py::test_daily_json_pins_schema` asserts top-level JSON
keys. Adding `projects` requires an intentional test update.

### Finding 7 - CSV fields are pinned

CSV tests assert exact headers. Keeping CSV unchanged avoids a breaking change
while still improving JSON.

### Finding 8 - Statusline can reuse live snapshot concepts

`live.py` already computes today's usage, trailing 7-day usage, cache savings,
pricing warnings, and rate-limit windows. A non-interactive statusline command
should reuse the same building blocks but produce plain text/JSON instead of a
Rich TUI.

## Blockers

No code blocker found. The main risk is accidental scope creep into synthetic
activity blocks or embedded query languages, both of which should stay out of
this implementation.
