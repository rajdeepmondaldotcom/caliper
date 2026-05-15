# Caliper 0.0.28 Final Live Release QA - Brutal Feedback

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.28`

## Verdict

`0.0.28` is the build I would put in front of Hacker News.

The release candidate keeps the `0.0.27` privacy and install fixes, closes the
last command-palette discoverability gap found during the code-quality pass, and
tightens the test coverage gate from the stale temporary 85% floor to 88%.

This is not mathematically perfect. It is launch-good: install works, trust
defaults are boring, the TUI keymap and palette now agree, the repo is much
cleaner than the launch workbench, and the remaining criticism is roadmap polish
rather than a reason to hold the release.

## What Was Tested

- PyPI metadata for the previously latest `caliper-ai==0.0.27`.
- `uvx --isolated --no-cache --from caliper-ai==0.0.27 caliper --version`.
- `pipx run --spec caliper-ai==0.0.27 caliper --version`.
- Published-package `CALIPER_SMOKE_VERSION=0.0.27 scripts/live-release-smoke.sh`.
- Empty first-run `overview` at 80 columns and compact 50 columns with all vendor
  roots isolated.
- Smoke artifact privacy grep for local paths, temp roots, state DB names, and
  session internals.
- Published-package Doctor redaction for Cursor-style encoded project paths.
- Published-package TUI demo navigation through all 13 shipped screens.
- Source audit for stale launch docs, TODO-style markers, type ignores, coverage
  weak spots, command palette coverage, release workflow shape, dependency
  footprint, and public docs drift.
- Full local quality gate after the `0.0.28` fix.

## P1 - Command Palette Did Not Actually Expose Every Screen

Personas: HN keyboard purist, accessibility reviewer, terminal power user.

The direct TUI shortcuts worked, but the command palette omitted newer screens:
Receipt, What-If, Budgets, Help, and Insights. That contradicted the palette's
own promise to expose every Caliper action by name.

Brutal feedback: this is exactly the kind of small inconsistency that makes a
polished terminal app feel unfinished. A keyboard-first user should not need to
know the secret keymap before search can find the screen.

Status: fixed in `0.0.28`.

## P2 - Coverage Is Good, But Not Yet 90%

Personas: external contributor, YC diligence reviewer, skeptical maintainer.

The final measured coverage is 88.88%. That is solid for a CLI/TUI app with live
terminal paths, but the repo still had a temporary 85% coverage floor comment.

Brutal feedback: shipping a public repo with "temporary 85" after calling the
release final is sloppy. If the bar is not 90 yet, say so directly and make the
gate closer to reality.

Status: improved in `0.0.28` by raising the gate to 88% and adding direct
command-palette discovery/search tests. The command-palette module now measures
93% coverage. The remaining target is 90% after more TUI worker and branch-path
coverage.

## P2 - CLI Surface Is Powerful But Dense

Personas: HN CLI pedant, first-time user, LinkedIn engineering manager.

The command surface is now broad enough to be useful, but root help still reads
like a serious maintainer tool. The first-run path needs to keep pushing three
commands: `overview`, `doctor`, and `tui --demo`.

Brutal feedback: the product wedge is strong. The first 30 seconds are still
where users can bounce because there is too much to scan.

Status: backlog, not a release blocker.

## P2 - Data-Source Scoping Is Still Easy To Misread

Personas: HN privacy skeptic, security reviewer, developer using temp fixtures.

Passing `--session-root` scopes OpenAI Codex sessions. It does not isolate
Claude Code, Cursor, or Aider unless their vendor roots are also pointed at temp
directories.

Brutal feedback: technically correct is not enough for privacy-sensitive tools.
The docs need to make multi-vendor discovery semantics impossible to misread.

Status: backlog, not a release blocker.

## Persona Attacks

### Hacker News Privacy Skeptic

"The redaction story is finally boring. I tried to get local paths and encoded
Cursor project names to leak; they stayed redacted. My remaining complaint is
that vendor discovery needs clearer wording."

### Hacker News CLI Purist

"The TUI was almost there, but the command palette missing screens was a real
paper cut. Fixing that makes the keyboard story coherent."

### YC Partner

"This is launchable. The repo now looks less like a frantic release workbench,
and the actual product promise is specific enough to understand quickly."

### Reddit First-Time User

"Demo mode works, empty state tells me what to do, and the TUI does not fall
apart when I mash keys. I still want less dense help text."

### LinkedIn Engineering Manager

"I can forward this to senior engineers. For team rollout, I want clearer docs
on exactly which local tools are read by default."

### External Contributor

"The tests are real and the release workflow is serious. The largest remaining
repo-quality smell is coverage not being back at 90% yet."

## Good Enough?

Release candidate `0.0.28`: yes.

The only package-affecting defect found in this pass was the incomplete command
palette. It is fixed, covered by targeted tests, and ready for the release gate.
