# Phase 5 - Plan Revision Round 2

## Refinements From Research

The Phase 1-3 direction holds. Research only tightens implementation details:

1. Keep the rate-card model.
   - OpenAI's Codex credit system is token-type based.
   - `pricing.py` already models Codex credits, API-equivalent dollars, fast
     multipliers, long-context events, and source warnings.
   - No LiteLLM dependency is added.

2. Keep JSON enrichment scoped.
   - JSON is the right surface for full project inventories.
   - CSV and Markdown stay stable.

3. Keep Prometheus conservative.
   - Do not emit project paths or git origins as labels.
   - Existing metric naming remains aligned with Prometheus guidance.

4. Keep statusline low-dependency.
   - Plain text and JSON only.
   - No Rich layout and no persistent daemon.

5. Keep docs explicit about sensitive exports.
   - JSON project inventories may include local paths and git origin URLs.
   - README privacy language must mention this.

6. Treat subscription data as explainability metadata.
   - Preserve raw `plan_type`, `limit_id`, and `limit_name`.
   - Normalize known subscription plan strings for readability.
   - Warn instead of guessing when access is promotional, unknown, or
     Enterprise-family billing may depend on workspace migration.

7. Prefer the main limit bucket for summary windows.
   - Keep all raw samples available in limits/JSON.
   - Use the logged `codex` bucket for default primary/secondary window math
     when model-specific preview buckets also exist.

## Updated Acceptance Criteria

- Existing reports still parse JSONL locally and run offline by default.
- JSON exact amount fields are additive and backward-compatible.
- Project provenance does not alter table/CSV/Markdown schemas.
- Limit IDs are additive in limits exports.
- Subscription warnings are visible without changing cost formulas.
- Statusline works in non-interactive command contexts.
- No network call is introduced outside explicit `rates refresh`.
