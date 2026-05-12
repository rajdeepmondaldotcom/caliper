# Phase 4 - Industry Standards Research

Research refined the plan but did not change the architecture.

## Sources

- GitHub repository: `https://github.com/ryoppippi/ccusage`
- Codex package README: `https://github.com/ryoppippi/ccusage/tree/main/apps/codex`
- Codex docs: `https://ccusage.com/guide/codex/`
- Codex daily docs: `https://ccusage.com/guide/codex/daily`
- Codex monthly docs: `https://ccusage.com/guide/codex/monthly`
- Codex session docs: `https://ccusage.com/guide/codex/session`
- OpenAI Codex rate card:
  `https://help.openai.com/en/articles/20001106-codex-rate-card`
- OpenAI Codex subscription access:
  `https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan`
- OpenAI Codex pricing and usage limits:
  `https://developers.openai.com/codex/pricing`
- OpenAI API pricing: `https://openai.com/api/pricing/`
- JSON Lines format: `https://jsonlines.org/`
- XDG Base Directory Specification:
  `https://specifications.freedesktop.org/basedir-spec/latest/`
- Typer testing docs: `https://typer.tiangolo.com/tutorial/testing/`
- Prometheus naming practices:
  `https://prometheus.io/docs/practices/naming/`
- Python entry points specification:
  `https://packaging.python.org/en/latest/specifications/entry-points/`

## Findings Applied To Existing Plan

### Codex CLI feature baseline

The referenced Codex package focuses on daily, monthly, and session reports over
Codex JSONL files. Its docs emphasize token deltas, per-model grouping,
cache-read accounting, JSON output, compact tables, timezone/date filtering, and
offline pricing.

`codex-meter` already supports those surfaces and more. The plan should not
redesign the tool around the external package. It should fill explainability
gaps inside the existing modules.

### Token and pricing visibility

OpenAI's Codex rate-card FAQ says token-based credit usage is intended to make
input, cached input, and output contributions clearer. OpenAI API pricing also
separates input, cached input, and output rates for current flagship models.

This supports preserving exact amount fields and project-level provenance so
users can connect credit movement to actual local activity.

### Subscription and limit metadata

OpenAI's Codex plan documentation distinguishes subscription access, promotional
access, token-priced workspaces, and usage-limit dashboards. Local logs already
carry `plan_type` and rate-limit buckets, so the implementation should expose
that metadata directly instead of inventing pricing multipliers. The safe
refinement is to normalize known plan labels, preserve raw values, and warn
when a plan's billing semantics are ambiguous.

### JSONL handling

JSON Lines requires UTF-8, one valid JSON value per line, and `\n` line
terminators. The existing parser already opens files as UTF-8 with replacement
and skips invalid JSON lines. No parser rewrite is needed.

### Configuration and cache placement

The XDG spec defines `$XDG_CONFIG_HOME` and `$XDG_CACHE_HOME` defaults and says
relative environment paths should be ignored. `parse_cache.py` already honors
`XDG_CACHE_HOME`; this implementation should avoid changing config precedence
while adding command features.

### CLI testing

Typer recommends `CliRunner` for command tests. The repository already follows
that pattern, so new statusline and JSON-schema tests should use the same test
style.

### Prometheus metrics

Prometheus naming guidance favors an application prefix, single units, and
labels for dimensions. Existing metrics use the `codex_meter_` prefix and labels
for model/tier/kind. Project provenance work should not add high-cardinality
project path labels to Prometheus in this pass.

### Packaging

The PyPA entry point specification confirms the current `[project.scripts]`
console command shape. No packaging change is needed for the new subcommand.

## Research-Bounded Decisions

- Add a statusline command because it is a useful compact UX pattern and can be
  built on existing code.
- Do not add an embedded JQ engine.
- Do not add project paths as Prometheus labels.
- Do not make normal reports fetch pricing over the network.
- Do not replace the Codex-specific rate card with a LiteLLM dependency.
