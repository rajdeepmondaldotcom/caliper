# Domain docs

This is a single-context repository.

Agents should read these files before architecture, diagnosis, or TDD work:

- `CLAUDE.md` for the current module map, invariants, and workflow.
- `CONTEXT.md` if present for project domain vocabulary.
- `docs/adr/` if present for architecture decisions that should not be re-litigated.

If `CONTEXT.md` or `docs/adr/` do not exist, infer vocabulary from `CLAUDE.md`, the code, tests, and README, then propose durable docs only when the decision is likely to matter in future work.
