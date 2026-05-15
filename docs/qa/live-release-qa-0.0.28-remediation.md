# Caliper 0.0.28 Final Live Release QA - Remediation

Date: 2026-05-15 IST
Target reviewed: `caliper-ai==0.0.27`
Fixed release: `0.0.28`

## Summary

The final code-quality pass found one user-facing TUI polish defect worth
shipping: the command palette did not list every shipped screen. The direct
shortcuts worked, but palette discovery lagged behind the screen set.

`0.0.28` fixes that gap, raises the coverage gate from 85% to 88%, and adds this
final QA record with the code-quality critique requested for launch review.

## Actions Taken

- Added command-palette entries for Receipt, What-If, Budgets, Help, and
  Insights.
- Added targeted TUI assertions so the palette keeps the newer screen actions
  and the provider discovery/search path is exercised.
- Bumped the package version to `0.0.28`.
- Added the `0.0.28` changelog entry.
- Raised `coverage.fail_under` from 85 to 88 after measuring 88.88% total
  coverage.
- Added the `0.0.28` brutal-feedback report with UX, privacy, and code-quality
  findings.
- Added this remediation report.

## Verification Completed

- `uvx --isolated --no-cache --from caliper-ai==0.0.27 caliper --version`
- `pipx run --spec caliper-ai==0.0.27 caliper --version`
- `CALIPER_SMOKE_VERSION=0.0.27 scripts/live-release-smoke.sh`
- Empty first-run `overview` at 80 columns and compact 50 columns.
- Published-package smoke output privacy grep for local paths and temp roots.
- Published-package Doctor encoded-path redaction probe.
- Published-package TUI navigation probe across 13 screens.
- `uv run pytest tests/tui/test_screens_smoke.py::test_palette_provider_loads tests/tui/test_screens_smoke.py::test_palette_provider_discovers_and_searches_new_screen_actions`
- `uv run pytest tests/tui/test_screens_smoke.py::test_palette_provider_loads tests/tui/test_navigation.py::test_tui_navigation_keymap`
- `uv run ruff check src/caliper/tui/palette.py tests/tui/test_screens_smoke.py pyproject.toml CHANGELOG.md`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `cd docs-site && npm audit --audit-level=high --cache .npm-cache`
- `cd docs-site && npm run build -- --silent`
- `uv run pytest` (`551 passed`)
- `uv run pytest --cov=src/caliper --cov-report=term --cov-report=xml`
- `scripts/release-smoke.sh`
- `CALIPER_SMOKE_PACKAGE=. scripts/live-release-smoke.sh`
- `uv build`
- `uvx twine check dist/*`
- Built-wheel version, Doctor encoded-path redaction, command-palette
  completeness, and TUI navigation probe.

## Remaining Backlog

- Lift coverage to 90% after adding deeper TUI worker and branch-path tests.
- Clarify in docs/help that `--session-root` scopes Codex only; isolating all
  vendors requires vendor-specific roots.
- Reduce root help density or add a stronger first-run "three commands" path.
- Improve TUI footer affordances so global shortcuts are visible on more
  screens without opening Help.
