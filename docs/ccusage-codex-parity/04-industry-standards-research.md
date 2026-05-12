# Phase 4 - Industry Standards Research

Research refined details only. The Phase 1-3 plan remains the source of truth.

## Sources

- `@ccusage/codex` npm metadata:
  `https://registry.npmjs.org/@ccusage/codex`
- `@ccusage/codex` 18.0.11 tarball inspected locally with `npm pack`.
- Codex daily docs: `https://ccusage.com/guide/codex/daily`
- ccusage CLI options: `https://ccusage.com/guide/cli-options`
- ccusage JSON output: `https://ccusage.com/guide/json-output`
- ccusage GitHub README: `https://github.com/ryoppippi/ccusage`
- Codex CLI docs: `https://developers.openai.com/codex/cli`
- OpenAI Codex rate card:
  `https://help.openai.com/en/articles/20001106-codex-rate-card`
- OpenAI Codex pricing and usage limits:
  `https://developers.openai.com/codex/pricing`
- OpenAI Codex source for config home behavior:
  `https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/src/config/mod.rs`

## Findings Grounded In The Plan

### Finding 1 - The package is much smaller than its parent CLI

`@ccusage/codex` 18.0.11 exposes only `daily`, `monthly`, and `session`. The
bundled CLI help confirms shared flags for JSON, since/until, timezone, locale,
offline, compact, and color.

Impact:

- Do not copy broad parent-CLI features that the Codex package does not expose.
- The Python tool already exceeds command coverage.
- Focus on the missing data-quality features rather than command count.

### Finding 2 - `CODEX_HOME` is part of the Codex ecosystem

The `@ccusage/codex` README says the CLI looks under `CODEX_HOME`, defaulting to
`~/.codex`. OpenAI's Codex source documents the effective Codex home as a
directory defaulting to `~/.codex` and overridable by the `CODEX_HOME`
environment variable.

Impact:

- Add `CODEX_HOME` support for default paths.
- Preserve explicit `--session-root`, `--state-db`, and `--codex-config`
  overrides because local CLI flags must remain strongest.

### Finding 3 - Row-level model breakdowns are a real integration feature

`@ccusage/codex` JSON rows include per-model usage objects. The public docs also
call out per-model token summaries. This is useful for downstream scripts that
want the model mix inside each day, month, or session without rejoining a
separate top-level inventory.

Impact:

- Keep `model_mode` for whole-window analysis.
- Add row-local `model_breakdowns` for integration ergonomics.
- Make this JSON-only to avoid table/schema churn.

### Finding 4 - Fallback model visibility prevents quiet mispricing

`@ccusage/codex` marks fallback model entries with `isFallback` when legacy
Codex logs lack model metadata. Its docs explain that early logs without model
metadata need an assumed model so usage is not dropped.

Impact:

- `codex-meter` should not silently treat default-model fallback as fully
  observed.
- Add source and fallback flags instead of changing the pricing formula.
- Existing pricing warnings remain responsible for unknown or partial rates.

### Finding 5 - OpenAI's Codex rate card supports token-type transparency

OpenAI's rate card says Codex usage maps directly to input, cached input, and
output credits per million tokens, and that this format helps users see how each
token type contributes to usage.

Impact:

- Row-level model breakdowns should include input, cached input, output,
  reasoning output, total tokens, credits, and API-dollar estimates.
- Exact decimal strings should accompany float fields where costs are emitted.

### Finding 6 - Offline-first remains the right local default

`@ccusage/codex` can fetch LiteLLM pricing unless offline is requested. This
project already uses explicit `rates refresh --allow-network` and source-audited
embedded Codex pricing. That direction is more conservative for a local usage
intelligence tool and has been documented in earlier plans.

Impact:

- Do not add implicit network fetches.
- Keep research as validation for explicit pricing provenance, not a redesign.

## Risks

- Adding model-breakdown payloads increases JSON size. This is acceptable
  because JSON is the integration surface and table/CSV/Markdown stay stable.
- `CODEX_HOME` can point to missing data. Existing doctor/parser warnings should
  surface that without special cases.
- Fallback counts may be mistaken for pricing errors. README wording should
  explain that fallback means model identity was inferred, not that token counts
  were missing.

