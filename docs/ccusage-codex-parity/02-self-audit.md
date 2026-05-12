# Phase 2 - Self-Audit

## Audit Method

Compared the Phase 1 plan against these local implementation surfaces:

- `src/codex_meter/config.py`
- `src/codex_meter/models.py`
- `src/codex_meter/parser.py`
- `src/codex_meter/parse_cache.py`
- `src/codex_meter/aggregation.py`
- `src/codex_meter/render.py`
- `src/codex_meter/statusline.py`
- `src/codex_meter/cli.py`
- `tests/test_config.py`
- `tests/test_parser.py`
- `tests/test_aggregation.py`
- `tests/test_formats.py`
- `tests/test_parse_cache.py`

## Findings

### Finding 1 - `CODEX_HOME` belongs in config defaults

Status: plan confirmed.

`build_options()` is the single place that resolves default paths after merging
CLI flags and config files. Adding `CODEX_HOME` at module default import time
would make tests brittle, because environment changes after import would not be
seen. Use helper functions at option-build time instead.

### Finding 2 - Event-level model source is required

Status: plan confirmed.

Fallback visibility cannot be reliably reconstructed from aggregate labels
because `options.default_model` may be a real known model. The parser must record
whether the model came from event context, SQLite metadata, or default fallback.

### Finding 3 - `ThreadMeta.model` currently conflates state and context

Status: plan needs precision.

`update_context_from_event()` writes `turn_context.model` into
`current_meta.model`. Later parser code checks `current_meta.model` and
`thread_meta.model`, but after a turn context the two are no longer equivalent.
The model-source resolver should compare current and original metadata in order
instead of only looking at values.

### Finding 4 - `Aggregate.add_event()` is the right breakdown hook

Status: plan confirmed.

`aggregate_events()` already computes event cost and cache savings once per
event. Adding model-breakdown updates inside `Aggregate.add_event()` avoids
recomputing costs and keeps all aggregate surfaces consistent.

### Finding 5 - Recursive aggregate reuse would be unsafe

Status: implementation detail added.

Using nested `Aggregate` objects for model breakdowns would risk recursive child
creation and oversized payloads. Use a separate `ModelBreakdown` dataclass with
only fields needed for model/tier JSON.

### Finding 6 - JSON additions are backward-compatible for tests

Status: plan confirmed.

Existing tests pin top-level JSON keys, not every aggregate field. Adding fields
inside `totals`, `breakdowns`, `projects`, and `model_mode` should be additive.
Still add focused assertions so the new contract is intentional.

### Finding 7 - Parse-cache event decoding is currently less tolerant than thread decoding

Status: implementation required.

`_thread_from_dict()` filters unknown keys, but `_event_from_dict()` passes the
whole raw object into `UsageEvent(**item)`. Add equivalent field filtering so
future cache payloads do not crash older binaries.

### Finding 8 - Statusline should inherit aggregate fallback visibility later

Status: no Phase 7 blocker.

`statusline.py` uses `aggregate_total()` and report pricing warnings. Once
aggregate fallback counts exist, statusline JSON could expose them, but the core
value is report JSON. Avoid broadening statusline unless tests reveal a gap.

## Blockers

No blockers found.

## Scope Guardrails

- Do not introduce a second parser.
- Do not add network-dependent pricing during normal reports.
- Do not change table/CSV/Markdown schemas.
- Do not add locale formatting in this pass.
- Do not run Terraform.

