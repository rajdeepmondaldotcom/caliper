# Phase 4 - Industry Standards Research

## Research Boundary

This research validates the Phase 1-3 plan. It does not redesign the system.
The original direction remains the source of truth:

- preserve public behavior;
- deepen modules around existing interfaces;
- keep the default path offline;
- make research-driven refinements only.

## Sources Consulted

- [PyPA: src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
- [PyPA: creating and packaging command-line tools](https://packaging.python.org/en/latest/guides/creating-command-line-tools/)
- [pytest: good integration practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
- [Typer: testing](https://typer.tiangolo.com/tutorial/testing/)
- [Typer: commands and subcommands](https://typer.tiangolo.com/tutorial/commands/)
- [mypy: using mypy with an existing codebase](https://mypy.readthedocs.io/en/stable/existing_code.html)
- [Bandit: getting started](https://bandit.readthedocs.io/en/latest/start.html)
- [Bandit: configuration](https://bandit.readthedocs.io/en/latest/config.html)
- [coverage.py: configuration reference](https://coverage.readthedocs.io/en/7.10.7/config.html)
- [Ruff: configuration](https://docs.astral.sh/ruff/configuration/)
- [Python subprocess security considerations](https://docs.python.org/3/library/subprocess.html#security-considerations)
- [Python sqlite3 parameter substitution](https://docs.python.org/3/library/sqlite3.html#how-to-use-placeholders-to-bind-values-in-sql-queries)
- [Python urllib.request](https://docs.python.org/3/library/urllib.request.html)
- [Python decimal](https://docs.python.org/3/library/decimal.html)
- [OpenAI API pricing](https://openai.com/api/pricing/)
- [OpenAI GPT-5.5 model docs](https://developers.openai.com/api/docs/models/gpt-5.5)
- [OpenAI Help: Codex rate card](https://help-lb.openai.com/en/articles/20001106-codex-rate-card)
- [OpenAI Developers: Codex pricing](https://developers.openai.com/codex/pricing)

## Research Findings

### Packaging and CLI layout

PyPA documents the `src/` layout as a way to avoid accidentally importing the
in-development copy of a package when testing and packaging. The repo already
uses `src/codex_meter`, Hatchling, and a `project.scripts` entry point, which
matches the PyPA shape for installable CLI tools.

Refinement:

- Keep the current package layout.
- Keep `codex-meter = "codex_meter.cli:app"` as the entry point.
- Do not split Typer command registration into many entry points. Extract support
  logic underneath the current CLI surface instead.

Impact on plan:

- Confirms the plan to keep `cli.py` as command routing while moving domain logic
  into focused modules.

### CLI testing

Typer documents `CliRunner` as the direct testing path for Typer apps. The repo
already uses this pattern. Pytest recommends tests outside application code, and
the repo already has `tests/` outside `src/`.

Refinement:

- Keep CLI smoke tests for command contracts.
- Move pure behavior assertions from `codex_meter.cli` private helpers to the
  extracted modules.
- Add direct tests for extracted modules so CLI tests do not become the only
  safety net.

Impact on plan:

- Confirms the test strategy in Phase 3.
- Strengthens the requirement that private helper tests move with their modules.

### Static typing

Mypy recommends starting small on existing codebases, checking the same files
consistently, and using per-module configuration when only part of a project is
ready. It also recommends annotating widely imported modules early.

The repo ships `py.typed`, so static typing is desirable. However, current mypy
results show the Decimal model needs a focused cleanup before a hard gate is
fair.

Refinement:

- Do not add a hard whole-package mypy CI gate in this cleanup pass.
- Improve type clarity when touching extracted modules.
- Prefer Decimal fields that are statically Decimal after construction in a later
  focused typing pass.

Impact on plan:

- Keeps mypy out of the required final gate for now.
- Adds a post-cleanup recommendation for a Decimal typing pass.

### Linting and formatting

Ruff supports configuration in `pyproject.toml` and the repo already uses Ruff
for linting, import sorting, pyupgrade, bugbear, and simplify rules. Ruff also
respects project config discovery.

Refinement:

- Keep Ruff as the required linter and formatter.
- Do not add overlapping style tools.
- Run `ruff check` and `ruff format --check` after each meaningful extraction.

Impact on plan:

- Confirms the current quality toolchain.

### Coverage

Coverage.py supports TOML config in `pyproject.toml`, branch coverage, missing
line reporting, and `fail_under`. The repo already enables branch coverage and
shows missing lines.

Refinement:

- Add a conservative coverage floor only after implementation is stable.
- Set the floor below or equal to the observed stable coverage, not above it.
- Keep `show_missing = true` because it helps target future cleanup.

Impact on plan:

- Supports adding `fail_under = 85` if post-implementation coverage remains above
  that floor.

### Security scanning

Bandit supports recursive scans and config through `pyproject.toml`. It also
supports baselines and skips. Current Bandit findings are explainable but not
zero:

- static subprocess calls to `git` and `codex`;
- explicit opt-in `urlopen`;
- fixed-schema SQL string assembly.

Python subprocess docs state that the library does not implicitly call a shell,
and that shell injection risk mainly appears when `shell=True` is used. The docs
also recommend using fully qualified executable paths or `shutil.which()` for
maximum reliability.

Python sqlite3 docs warn against string formatting for SQL values and recommend
parameter substitution. This repo's dynamic query builds fixed column expressions
from known column names, not user-supplied values, but the code should make that
allowlist clearer.

Python urllib docs show `urlopen` as valid for HTTP(S), returning bytes and
supporting context-manager usage. Bandit still flags it because arbitrary URL
schemes can be risky.

Refinement:

- Keep `shell=False` static subprocess calls.
- Prefer a small helper that resolves `git`/`codex` with `shutil.which()` when
  adding a Bandit gate, but do not change behavior in this pass unless low risk.
- Validate pricing-source URL schemes before calling `urlopen`.
- Make fixed-schema SQL allowlisting obvious enough for maintainers and scanners.
- Do not add a hard Bandit gate unless intentional findings are suppressed.

Impact on plan:

- Add URL scheme validation in `rate_audit.py`.
- Keep Bandit as a documented audit command, not a CI gate, unless findings are
  explicitly suppressed.

### Decimal cost arithmetic

Python's `decimal` docs emphasize exact decimal representation and accounting
use cases. This supports the repo's current choice to use Decimal internally for
pricing and exact JSON strings.

Refinement:

- Preserve Decimal arithmetic internally.
- Do not simplify cost code by converting core calculations to float.
- Improve type annotations around Decimal as a cleanup path, not by weakening
  monetary precision.

Impact on plan:

- Confirms exact Decimal behavior as a core invariant.
- Adds a constraint to scenario extraction: deltas must remain Decimal-backed
  until compatibility fields are rendered.

### OpenAI/Codex pricing and limits

Official OpenAI API pricing lists GPT-5.5, GPT-5.4, and GPT-5.4-mini token rates.
The GPT-5.5 model docs list the 1,050,000 context window, text token pricing, and
the `>272K` long-context multiplier. Official Codex docs describe token-based
credits per 1M input, cached input, and output tokens, plus plan and fast-mode
limit caveats.

Refinement:

- Do not change embedded rates during this cleanup unless a test proves drift.
- Preserve rate-source checked dates and `rates refresh --allow-network`.
- Preserve warnings for legacy or ambiguous plan cases.
- Keep rate-limit samples as observed local evidence, not guessed billing state.

Impact on plan:

- Confirms the current pricing architecture.
- Reinforces that this cleanup should not add feature-level pricing changes.

## Cross-Reference Against Revised Plan

| Plan area | Research result | Plan change |
| --- | --- | --- |
| Package layout | Current `src/` layout and entry point match PyPA guidance | No redesign |
| CLI shape | Typer supports command groups and CliRunner tests | Keep Typer surface, extract internals |
| Tests | pytest supports external tests and installed/editable package testing | Keep `tests/`, add module tests |
| Static typing | Mypy recommends gradual adoption | Defer hard whole-package mypy gate |
| Coverage | `fail_under` is supported | Add conservative floor only after refactor |
| Security | Bandit config and Python docs support targeted treatment | Validate URL schemes; no blind gate |
| Decimal | Decimal is appropriate for accounting-style exactness | Preserve Decimal internals |
| Pricing | Official OpenAI docs match current architecture | No pricing redesign |

## Final Research Decision

The revised plan remains valid. Research tightens it in four places:

1. Add URL scheme validation in the new rate-audit module.
2. Keep mypy and Bandit out of hard CI gates unless the code is cleaned up enough
   for them to pass intentionally.
3. Add a conservative coverage floor after the implementation remains green.
4. Preserve Decimal-first cost calculations and exact JSON fields.
