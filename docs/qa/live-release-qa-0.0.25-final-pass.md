# Caliper 0.0.25 Final Release QA Pass

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.25`

## Verdict

0.0.25 is the final clean release candidate after the 0.0.24 push.

The only concrete issue left after 0.0.24 was GitHub's high-severity
Dependabot alert in the docs-site npm lockfile. This pass updates the affected
transitive dependency and verifies the docs and package release surfaces again.

## Fixed

- Updated `docs-site/package-lock.json` so `devalue` resolves to `5.8.1`.
- Verified `npm audit --audit-level=high` reports zero vulnerabilities.
- Verified the Astro docs build still succeeds.

## Release Gate

Run before publish:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `cd docs-site && npm audit --audit-level=high`
- `cd docs-site && npm run build -- --silent`
- `scripts/release-smoke.sh`
- `uv build`
- `uvx twine check dist/*`
- local wheel live-release smoke
- local wheel `uvx` and `pipx` install checks

After publish:

- PyPI JSON must report `0.0.25`.
- Published `uvx`, `pipx`, and live-release smoke must pass.
- GitHub tag release workflow must pass.
