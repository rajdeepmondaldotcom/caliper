# Caliper 0.0.27 Final Live Release QA - Remediation

Date: 2026-05-15 IST
Target reviewed: `caliper-ai==0.0.27`
Fixed release: not required

## Summary

The `0.0.27` live release passed final QA. No package hotfix is required.

This remediation pass focuses on launch repo hygiene: keep current evidence and
release instructions, remove stale pre-release planning artifacts, and keep the
remaining public docs aligned with the shipped product.

## Actions Taken

- Added a `0.0.27` brutal-feedback report with persona-based critique and the
  final release verdict.
- Added this `0.0.27` remediation report.
- Retired superseded QA reports from `0.0.21` through `0.0.25`.
- Retired obsolete TUI/persona/release-overhaul planning docs that no longer
  describe the shipped product.
- Kept the current `0.0.26` QA reports because they explain the defects fixed in
  `0.0.27`.
- Kept `docs/release-and-ux-overhaul/RUNBOOK-publish.md` as the current manual
  release fallback.
- Updated live source/test references that pointed at removed planning docs.
- Removed ignored local build/cache artifacts from the working tree after
  verification.

## Verification Completed

- PyPI JSON reports `0.0.27`.
- `uvx --isolated --no-cache --from caliper-ai==0.0.27 caliper --version`
- `pipx run --spec caliper-ai==0.0.27 caliper --version`
- `CALIPER_SMOKE_VERSION=0.0.27 scripts/live-release-smoke.sh`
- Empty first-run `overview` at 80 columns with all vendor roots isolated.
- Empty first-run compact `overview --width 50` with all vendor roots isolated.
- Published-package Doctor encoded-path redaction probe.
- Published-package TUI navigation probe.
- Smoke output privacy grep for local paths and fixture identifiers.
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest` (`551 passed`)
- `cd docs-site && npm audit --audit-level=high --cache .npm-cache`
- `cd docs-site && npm run build -- --silent`
- `scripts/release-smoke.sh`
- `CALIPER_SMOKE_PACKAGE=. scripts/live-release-smoke.sh`
- `uv build`
- `uvx twine check dist/*`
- Built-wheel Doctor encoded-path redaction probe.
- Built-wheel TUI navigation probe.

## Remaining Backlog

- Clarify in docs/help that `--session-root` scopes Codex only; isolating all
  vendors requires vendor-specific roots or the smoke-test environment.
- Reduce root help density or add a stronger first-run "three commands" path.
- Improve TUI footer affordances so global shortcuts are visible on more screens.
