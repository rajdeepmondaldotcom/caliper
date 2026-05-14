# Caliper 0.0.24 Final Release QA Pass

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.24`

## Verdict

0.0.24 is good enough for the final live release and a serious Show HN/public
beta push.

This is still not "perfect UI/UX" in the absolute sense. No real product is.
But the 0.0.23 trust-polish blockers were closed, no P0/P1 release blocker is
known from this pass, and the published package installs and smokes from PyPI.

## 0.0.23 Blockers Closed

- Default JSON now redacts repo/session identity: git origins, git branches,
  git SHAs, session IDs, and session filenames are hidden unless `--show-paths`
  is passed.
- Narrow tables reserve the cost cell and drop lower-priority columns before
  money can render as `$0...`.
- Mixed uncovered pricing now reports `partial`; pure vendor-reported Aider
  cost still reports `vendor-reported`.
- Zero-baseline compare deltas now render `null` in JSON and `n/a` in human
  formats instead of false `0.00%` percentages.
- Budget JSON now uses stable `used_percent` precision and includes
  `used_percent_exact`.
- `rates catalog` table rates and context windows are formatted for humans.
- `advise --width`, `whatif --no-cache`, and `budgets check --no-cache` work
  when flags are placed after the subcommand.
- TUI global shortcuts work across secondary screens; Escape preserves Home;
  `NO_COLOR=1` pins theme cycling to monochrome; rate-limit panels show explicit
  usage percentages outside the progress bar.

## Verification

- `uv run ruff check .` passed.
- `uv run ruff format --check .` passed.
- `uv run pytest` passed: `546 passed`.
- `scripts/release-smoke.sh` passed.
- Built `dist/caliper_ai-0.0.24-py3-none-any.whl` and
  `dist/caliper_ai-0.0.24.tar.gz`.
- `uvx twine check dist/*` passed.
- Local wheel live-release smoke passed.
- Local wheel install checks passed with both `uvx` and `pipx`.
- `scripts/publish.sh` reran tests, ruff, format check, build, twine check, and
  uploaded 0.0.24 to PyPI.
- PyPI JSON verified `info.version == 0.0.24`.
- Published install checks passed:
  - `uvx --isolated --refresh --from caliper-ai==0.0.24 caliper --version`
  - `pipx run --spec caliper-ai==0.0.24 caliper --version`
  - `CALIPER_SMOKE_VERSION=0.0.24 scripts/live-release-smoke.sh`

## Residual Risk

The release is ready. Remaining critique is product-shaping work, not a release
blocker: keep improving first-run copy, TUI density, docs examples, and deeper
real-world multi-vendor fixtures after launch.
