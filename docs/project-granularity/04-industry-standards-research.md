# Phase 4 - Industry Standards Research

## Research Scope

The Phase 1-3 plan is the anchor. Research was used only to validate and refine
the implementation details around local Codex data, JSONL parsing, observability
metadata, read-only SQLite access, git/workspace identity, and privacy.

## Sources Consulted

- OpenAI Codex CLI docs:
  - `https://developers.openai.com/codex/cli`
  - `https://developers.openai.com/codex/config-reference`
- OpenAI Codex repository README:
  - `https://raw.githubusercontent.com/openai/codex/main/README.md`
- JSON Lines implementation guidance:
  - `https://jsonlines.readthedocs.io/en/latest/`
- SQLite URI filename docs:
  - `https://www.sqlite.org/uri.html`
- OpenTelemetry naming guidance:
  - `https://opentelemetry.io/docs/specs/semconv/general/naming/`
- OWASP Logging Cheat Sheet:
  - `https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html`
- Git `rev-parse` docs:
  - `https://git-scm.com/docs/git-rev-parse/2.22.0.html`

## Findings Grounded In The Plan

### Finding 1 - Codex is explicitly local and workspace-oriented

OpenAI's Codex CLI docs describe the CLI as a local terminal agent that can read,
change, and run code in the selected directory. The config reference also
documents user-level `~/.codex/config.toml` and project-scoped
`.codex/config.toml` files.

Impact on plan:

- Using local workspace path as the primary project identity is aligned with
  Codex's local selected-directory model.
- Documenting workspace attribution order in README is useful because Codex can
  have both global and project-scoped config.
- No architecture change needed.

### Finding 2 - JSONL should stay streaming and tolerant

JSON Lines guidance emphasizes one valid JSON value per line encoded as UTF-8,
with practical concerns around validation, helpful error handling, and text/binary
stream handling.

Impact on plan:

- Keep the current line-by-line parser.
- Continue skipping malformed JSONL lines rather than failing the whole report.
- Avoid loading whole files into memory for project tracking.
- No architecture change needed.

### Finding 3 - SQLite read-only URI mode is correct

SQLite documents URI filenames and `mode=ro` as a way to open a database
read-only.

Impact on plan:

- Keep `sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)`.
- Do not introduce writes to the Codex state DB.
- Dynamic column checks remain the correct compatibility strategy.

### Finding 4 - Metadata should use explicit, stable names

OpenTelemetry naming guidance recommends lowercase names, namespaces, singular
names for single entities, plural names for arrays, and avoiding reserved
namespaces for custom data.

Impact on plan:

- Use direct JSON field names such as `project_paths`, `project_names`,
  `git_origins`, `git_branches`, `git_shas`, `session_count`, `first_seen`, and
  `last_seen`.
- Keep arrays plural and scalar values singular.
- Do not invent `otel.*` fields or claim OpenTelemetry compliance.

### Finding 5 - Privacy guidance supports metadata-only tracking

OWASP logging guidance says event data should be consistent and useful, while
also excluding or sanitizing sensitive data. It specifically calls out
sanitization and avoiding unnecessary sensitive data in logs.

Impact on plan:

- Do not inspect prompt text, tool outputs, stdout/stderr, or message bodies for
  project identity.
- Use structural metadata: `turn_context.cwd`, SQLite `threads.cwd`, and git
  fields already stored by Codex.
- Keep default table behavior conservative; JSON exports can contain local
  metadata and should be documented as sensitive.

### Finding 6 - Git root discovery is a future refinement, not this plan

Git documents `git rev-parse --show-toplevel` for moving to or identifying the
top-level working tree.

Impact on plan:

- The current implementation should not shell out per event or scan user repos.
- Codex already records `cwd`, git origin, branch, and SHA in state DB; use that
  evidence first.
- A future explicit command could normalize arbitrary command `cwd` values to
  repo roots, but this implementation stays anchored to recorded Codex metadata.

## Risks Surfaced By Research

- Local paths and git remotes are sensitive metadata. README must say JSON
  exports may contain them.
- Adding top-level JSON fields is an intentional output expansion. Tests should
  pin the new shape.
- If future Codex versions change JSONL event names, the parser should continue
  to degrade gracefully.

## Decision

Proceed with the Phase 3 architecture. Research tightens naming, privacy, and
read-only data-source handling, but does not redirect the implementation.
