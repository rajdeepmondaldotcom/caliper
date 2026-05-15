# Caliper 0.0.26 Final Live Release QA - Remediation

Date: 2026-05-15 IST
Target reviewed: `caliper-ai==0.0.26`
Fixed release: `0.0.27`

## Summary

The final `0.0.26` live QA pass found two P1 launch-polish defects:

- CLI Doctor leaked local diagnostic paths by default.
- TUI keyboard navigation had a fast-navigation header race and a focused-input
  navigation trap on What-If.

Both are fixed in the working tree. `0.0.26` should not be promoted as the final
Show HN build; use `0.0.27` after the release gate and published-package smoke
pass.

## Fixed Before Release

- `caliper doctor` now redacts diagnostic `detail` fields by default across
  human table, JSON, Markdown, and CSV output.
- `caliper doctor --show-paths` restores explicit path reveal behavior for users
  who intentionally need local diagnostic paths.
- Doctor warning summaries now redact parser-warning example paths by default.
- Default redaction now also catches local paths encoded into vendor folder names,
  such as Cursor project directories.
- TUI screens now use a Caliper-owned stable header instead of Textual's built-in
  `Header`, avoiding delayed `HeaderTitle` callbacks after screen teardown.
- TUI global navigation now awaits screen pop/push transitions before continuing.
- What-If input global shortcut handling now schedules app navigation after the
  input key handler returns, so focused empty inputs no longer trap navigation.
- Focused regression coverage now exercises Doctor redaction, TUI screen
  navigation, screenshot matrices, focused What-If navigation, and app refresh.

## Remaining Polish Backlog

- Root CLI help is still dense. It is acceptable for a serious CLI, but first-run
  docs and launch copy should keep steering users to `overview`, `doctor`, and
  `tui --demo`.
- Some TUI secondary-screen footers still under-advertise the full global
  shortcut map. Functionality is fixed; discoverability can still improve.
- `pipx run` can warn when another `caliper` executable already exists on local
  `PATH`. This is normal `pipx` behavior and should be explained when sharing
  release evidence from a contributor checkout.

## Verification Completed

- `uvx --isolated --refresh --from caliper-ai==0.0.26 caliper --version`
- `pipx run --spec caliper-ai==0.0.26 caliper --version`
- `CALIPER_SMOKE_VERSION=0.0.26 scripts/live-release-smoke.sh`
- Empty first-run `overview` human output
- Empty first-run `overview --format json`
- Empty first-run `overview --compact --width 50`
- Published `caliper tui --demo --no-watchdog` launch smoke
- `uv run ruff check src/caliper/cli.py src/caliper/tui/app.py src/caliper/tui/screens/_base.py src/caliper/tui/screens/home.py src/caliper/tui/screens/whatif.py src/caliper/tui/widgets/app_header.py tests/test_init_doctor.py`
- `uv run pytest tests/test_init_doctor.py tests/tui/test_navigation.py tests/tui/test_launch_hardening.py tests/tui/test_home_snapshot.py tests/tui/test_app_refresh.py`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `cd docs-site && npm audit --audit-level=high`
- `cd docs-site && npm run build -- --silent`
- `scripts/release-smoke.sh`
- `CALIPER_SMOKE_PACKAGE=. scripts/live-release-smoke.sh`
- `uv build`
- `uvx twine check dist/*`
- Local built-wheel Doctor encoded-path redaction probe.
- Local built-wheel TUI navigation probe.
- PyPI accepted `dist/caliper_ai-0.0.27-py3-none-any.whl`.
- PyPI accepted `dist/caliper_ai-0.0.27.tar.gz`.
- PyPI JSON reports `0.0.27`.
- `uvx --isolated --no-cache --from caliper-ai==0.0.27 caliper --version`
- `pipx run --spec caliper-ai==0.0.27 caliper --version`
- `CALIPER_SMOKE_VERSION=0.0.27 scripts/live-release-smoke.sh`
- Published-package Doctor encoded-path redaction probe.
- Published-package TUI navigation probe.
