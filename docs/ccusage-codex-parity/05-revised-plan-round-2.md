# Phase 5 - Plan Revision Round 2

## Research-Informed Refinements

The original plan holds. Research only tightens behavior.

1. `CODEX_HOME`
   - Honor `CODEX_HOME` only for defaults.
   - Empty or whitespace-only values are ignored.
   - Config and CLI paths keep precedence.

2. Model fallback
   - Add `model_source` and `model_is_fallback` to each event.
   - Source labels are stable strings:
     `turn_context`, `state-db`, `default`.
   - Do not rename `default_model`; it remains the existing configurable
     fallback.

3. Model breakdown payloads
   - Use one row-local breakdown per `(model, service_tier)`.
   - Include token totals, credit/API-dollar totals, cache savings,
     pricing flags, model sources, fallback count, and first/last seen.
   - Sort by adjusted credits descending, then model and tier for stability.

4. Output compatibility
   - Add JSON fields only.
   - Do not change table, CSV, or Markdown.
   - Do not replace existing top-level `model_mode`.

5. Pricing
   - Keep embedded Codex rates and explicit `rates refresh`.
   - Do not fetch LiteLLM during normal reports.

6. Documentation
   - Mention that JSON can contain local paths, git remotes, model-source
     metadata, and inferred model flags.
   - Make clear that fallback-model visibility is explainability metadata.

## Updated Acceptance Criteria

- `CODEX_HOME` changes default Codex paths without affecting explicit paths.
- JSON aggregate objects include:
  - `model_sources`;
  - `fallback_model_events`;
  - `model_breakdowns`.
- Legacy/no-model events are included with fallback visibility.
- Existing top-level JSON schema keys remain unchanged.
- Tests and lint pass before implementation commits proceed to post-audit.

