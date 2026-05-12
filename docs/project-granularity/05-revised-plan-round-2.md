# Phase 5 - Revised Plan Round 2

## Research-Informed Refinements

The final implementation remains the Phase 3 plan with these refinements:

1. JSON field naming.
   - Use plural names for arrays: `sessions`, `project_paths`, `project_names`,
     `git_origins`, `git_branches`, `git_shas`, `agent_roles`, `sources`.
   - Use singular names for scalars: `session_count`, `first_seen`, `last_seen`.
   - Do not use `otel.*` or other reserved telemetry namespaces.

2. Privacy boundary.
   - Do not mine prompt text, tool outputs, stdout/stderr, or arbitrary message
     bodies.
   - README must explicitly say enriched JSON may include local paths and git
     remotes.

3. JSONL parser behavior.
   - Keep streaming reads.
   - Keep malformed-line tolerance.
   - Add only structural metadata extraction from `turn_context`.

4. SQLite behavior.
   - Keep read-only URI access.
   - Keep dynamic column detection.
   - Do not write to Codex state DB.

5. Git/workspace identity.
   - Use recorded Codex metadata rather than shelling out to git.
   - Do not normalize `exec_command_end.cwd` into repo roots in this pass.

6. Test strategy.
   - Pin the expanded JSON schema intentionally.
   - Confirm CSV field stability.
   - Confirm missing state DB workspace attribution.
   - Confirm parse-cache decode tolerance.

## Final Implementation Sequence

1. Data model and parser.
2. Aggregation provenance.
3. JSON report enrichment.
4. Tests.
5. README.
6. Verification.
7. Local commits only.
