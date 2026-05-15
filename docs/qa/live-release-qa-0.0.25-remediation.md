# Caliper 0.0.25 Final Live Release QA - Remediation

Date: 2026-05-15 IST
Fixed release: `0.0.26`

## Summary

The final `0.0.25` live QA pass found one P0 privacy blocker and two P1 release
trust issues. All launch blockers are fixed in the working tree.

The fixed release is `0.0.26`; do not promote `0.0.25` as the final Show HN
build.

## Fixed Before Release

- Statusline JSON now redacts `latest.session_id`, `latest.project`, and
  `top_project.label` by default.
- `caliper statusline --format json --show-paths` restores explicit reveal
  behavior for users who intentionally want local identity in output.
- `caliper rates catalog --format json` now redacts the local cache path and
  cache-miss warning path by default.
- `caliper rates catalog --format json --show-paths` restores the explicit cache
  path.
- `scripts/live-release-smoke.sh` isolates parse cache, XDG data, Claude Code,
  Cursor, and Aider roots.
- `scripts/release-smoke.sh` isolates Codex, Claude Code, Cursor, Aider, parse
  cache, and XDG data.
- Regression tests now cover statusline redaction, rates-catalog path redaction,
  and smoke-script vendor-root isolation.

## Remaining Polish Backlog

- TUI footer affordances are still sparse on several secondary screens. Global
  navigation works, but the UI does not always advertise it.
- The root help surface remains dense because it exposes a mature CLI command
  set and many aliases. This is acceptable for launch, but the first-run path
  should continue to bias toward `overview`, `doctor`, and `tui --demo`.
- `pipx run` may warn when a local `caliper` executable already exists on
  `PATH`; this is normal `pipx` behavior and not a Caliper defect.

## Verification Completed In Working Tree

- `uv run pytest tests/test_statusline.py tests/test_launch_hardening.py tests/test_privacy_invariant.py`
- `uv run pytest tests/test_commands.py::test_rates_catalog_empty_cache_surfaces_warning tests/test_statusline.py tests/test_launch_hardening.py`
- `uv run ruff check src/caliper/cli.py src/caliper/statusline.py tests/test_commands.py tests/test_statusline.py tests/test_launch_hardening.py`
- `CALIPER_SMOKE_PACKAGE=. scripts/live-release-smoke.sh`
- `scripts/release-smoke.sh`

## Release Verification Completed

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `cd docs-site && npm audit --audit-level=high`
- `cd docs-site && npm run build -- --silent`
- `scripts/release-smoke.sh`
- `CALIPER_SMOKE_PACKAGE=. scripts/live-release-smoke.sh`
- `uv build`
- `uvx twine check dist/*`
- PyPI accepted `dist/caliper_ai-0.0.26-py3-none-any.whl`.
- PyPI accepted `dist/caliper_ai-0.0.26.tar.gz`.
- PyPI JSON reports `0.0.26`.
- `uvx --isolated --refresh --from caliper-ai==0.0.26 caliper --version`
- `pipx run --spec caliper-ai==0.0.26 caliper --version`
- `CALIPER_SMOKE_VERSION=0.0.26 scripts/live-release-smoke.sh`
