# Phase 2 - Self-Audit

## Audit Method

Compared the Phase 1 plan to the actual code paths in:

- `src/codex_meter/parser.py`
- `src/codex_meter/models.py`
- `src/codex_meter/aggregation.py`
- `src/codex_meter/render.py`
- `src/codex_meter/parse_cache.py`
- `src/codex_meter/cli.py`
- `tests/test_parser.py`
- `tests/test_aggregation.py`
- `tests/test_formats.py`
- `tests/test_parse_cache.py`

## Findings

### Finding 1 - `ThreadMeta` is the right enrichment point

Status: plan confirmed.

`UsageEvent` stores a full `ThreadMeta`, and all grouping/reporting paths already
receive `UsageEvent`. Enriching `ThreadMeta` avoids a parallel project lookup
table and keeps metadata attached to event time.

### Finding 2 - `update_context_from_event()` currently ignores `cwd`

Status: implementation required.

The parser already watches `turn_context` for model, effort, and service tier.
Adding `cwd` handling there is a low-risk extension and directly addresses the
missing-state-DB case.

### Finding 3 - Aggregate rows currently lose provenance

Status: implementation required.

`Aggregate.add_event()` retains models, tiers, plan types, usage source, and
pricing flags, but it loses session IDs, local paths, git refs, and event time
span. The model extension should happen here rather than in render-only code so
future commands can reuse the same provenance.

### Finding 4 - JSON top-level schema is pinned by tests

Status: plan needs explicit test revision.

`tests/test_formats.py::test_daily_json_pins_schema` asserts the exact top-level
JSON keys. Adding `projects` requires updating that test intentionally.

### Finding 5 - CSV fields are pinned

Status: keep CSV unchanged in this pass.

`test_daily_csv_has_header_and_data` asserts the exact CSV field set. If project
metadata is added to CSV, that becomes a public breaking change. Keep the new
granularity in JSON for this implementation.

### Finding 6 - Parse cache decoder is too strict for future fields

Status: implementation required.

`_thread_from_dict(raw)` calls `ThreadMeta(**raw)`. It tolerates older payloads
when new dataclass fields have defaults, but it will not tolerate extra keys
from future cache versions. Since this task is already changing metadata shape,
make the decoder filter to known dataclass fields.

### Finding 7 - Top-level project inventory can reuse `aggregate_projects()`

Status: plan confirmed with a caveat.

`render.report_payload()` already computes `aggregate_total()` and
`aggregate_model_mode()`. Adding `aggregate_projects()` there keeps JSON payloads
consistent. It should pass the same `RateCard` object to avoid repeated rate
card loading.

### Finding 8 - Docs are ignored by `.gitignore`

Status: implementation workflow requirement.

The repository ignores `docs/`. These phase documents must be force-added if
they are meant to be committed with the local implementation history.

## Plan Gaps

- Add a helper for project display names rather than duplicating `Path(cwd).name`
  logic in `Aggregate.add_event()` and render code.
- Add workspace coverage as a helper in `render.py` to keep `report_payload()`
  readable.
- Include README documentation for enriched project JSON and workspace fallback.
- Update parser cache version number in the final plan.
