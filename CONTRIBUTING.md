# Contributing to Caliper

Caliper has a small surface and strong invariants. The contribution path
below exists so changes land without weakening them.

If you are not sure whether a change fits, open an issue first.

## The invariants that decide what we say yes to

These are not preferences. They are the reasons people trust the project.

1. **Offline by default.** No network call without an explicit
   `--allow-network` flag. The only file in `src/caliper` allowed to import
   `urllib`, `httpx`, or `requests` is the pricing-network chokepoint.
2. **One event shape.** Every new vendor parser projects into the same
   frozen `UsageEvent`. The aggregators, budgets, forecasts, insights,
   exporters, and Prometheus exporter must not change when a new vendor
   lands.
3. **Decimal money.** No `float(...)` on money. No float multiplication
   against a `Decimal`. Tests catch the regression.
4. **Privacy is enforced, not promised.** Redaction is on by default.
   Prompt text never reaches a `UsageEvent`. The privacy invariant has a
   test.
5. **Stable exit codes.** `caliper budgets check` and `caliper doctor`
   exit `0` ok, `1` warn, `2` fail. CI pipelines depend on this.
6. **Small runtime dependency list.** Today: `rich`, `typer`,
   `platformdirs`. The optional `[prom]` extra brings `prometheus-client`.
   Adding anything else requires a real reason.
7. **No telemetry.** Ever.

## Before you write code

1. Search the issue tracker. If there is no matching issue, open one with
   a one-paragraph description of the change.
2. For anything more than a typo, sketch the intent in two or three
   bullets in the issue. It saves both sides time.
3. If your change touches the public CLI or JSON output, call that out
   explicitly. Output is a contract.

## Development environment

```bash
git clone https://github.com/rajdeepmondaldotcom/caliper.git
cd caliper

uv sync --all-extras --dev

uv run ruff check .
uv run ruff format --check .
PYTHONWARNINGS=error::ResourceWarning uv run pytest
uv run pytest --cov=src/caliper --cov-report=term
uv run python -m build
bash scripts/release-smoke.sh
```

`uv` is required. The coverage floor is 90%. Do not lower it to pass a PR.

## Code style

- `ruff` is the only formatter and linter. Run `uv run ruff format .`
  before committing.
- Line length is 100.
- Public functions and dataclasses carry type annotations.
- Value objects are `@dataclass(frozen=True)`.

## Tests

- New features ship with tests in the same PR.
- Test names describe behavior, not structure
  (`test_returns_unattributed_bucket_when_no_commit_match`, not
  `test_attribution_method_returns_unattributed`).
- Fixtures live under `tests/fixtures/<topic>/`.
- For CLI tests, use `typer.testing.CliRunner` and pass
  `--codex-config <missing>` so the test does not pick up the
  developer's real `~/.codex/config.toml`.

## Pull request checklist

Before opening a PR:

- [ ] Tests pass: `uv run pytest`.
- [ ] Lint and format clean: `uv run ruff check . && uv run ruff format --check .`.
- [ ] Coverage floor holds: `uv run pytest --cov=src/caliper`.
- [ ] CHANGELOG updated under the right version or under `## Unreleased`.
- [ ] If the change touches CLI flags, JSON output, or exit codes, the
      change is called out in the PR body.
- [ ] If the change adds a vendor parser or pricing source, the rate-card
      `checked` date is updated where relevant.

PR titles follow Conventional Commits:

```
feat: claude code jsonl parser
fix: avoid float drift in cache_creation_input pricing
docs: clarify the --allow-network chokepoint
refactor: split load_usage into vendor orchestrators
test: lock the 0/1/2 exit-code matrix
chore: bump dependabot grouping window to weekly
```

## Common contributions

### Update a rate card

When a vendor publishes new pricing:

1. Edit `MODEL_CARDS` in `src/caliper/pricing.py`.
2. Update every `PRICING_SOURCES[*].checked` date to today.
3. Update the pricing section in the README to match.
4. Run `uv run pytest`. Pricing assertions drift. Fix them by manually
   recomputing the expected values from the formula in
   `test_pricing.py`.

### Add a vendor parser

1. Create `src/caliper/vendor_<name>.py` that returns `UsageEvent`
   objects.
2. Register it in `src/caliper/parser.py` and `src/caliper/vendors.py`.
3. Add fixtures under `tests/fixtures/<name>/` and a parser test.
4. Confirm `caliper vendors list` shows the new vendor and that
   `caliper doctor` does not regress.

### Add a schema change

Caliper exports JSON schemas under `schemas/`. If you add or change a
field on a public output:

1. Update the schema file.
2. Add a `caliper schema validate` test that exercises the new shape.
3. Note the field in CHANGELOG under the right version.

## Commit hygiene

- One logical change per commit.
- Each commit builds and passes tests on its own.
- Reference issues or findings the commit closes (`Closes #42`).

## Security disclosures

Do not open public issues for security bugs. See [SECURITY.md](SECURITY.md).

## Code of conduct

Caliper follows the
[Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By
participating you agree to uphold it.

## What we will respectfully decline

- A runtime dependency that is not on the small permitted list.
- A network call outside the pricing-refresh chokepoint.
- A change that breaks the `0 / 1 / 2` exit-code matrix.
- Floats anywhere on the money path.
- A new public command without a JSON output format.
- Telemetry or analytics of any kind.

## License

By contributing you agree that your contribution is licensed under the
project's MIT license.
