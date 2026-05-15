# Caliper 0.0.27 Final Live Release QA - Brutal Feedback

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.27`

## Verdict

`0.0.27` is good enough to promote as the current public release.

The package installs from PyPI, the live smoke suite passes, first-run empty
states are clear, default JSON outputs stay paste-safe, Doctor redacts both
normal and vendor-encoded local paths, and the packaged TUI survives rapid
keyboard navigation across the shipped screens.

This is not "perfect" in the literal sense. It is launch-good: no blocker found,
with remaining issues in discoverability, docs density, and repo hygiene.

## What Was Tested

- PyPI metadata for `caliper-ai==0.0.27`.
- `uvx --isolated --no-cache --from caliper-ai==0.0.27 caliper --version`.
- `pipx run --spec caliper-ai==0.0.27 caliper --version`.
- Published-package `CALIPER_SMOKE_VERSION=0.0.27 scripts/live-release-smoke.sh`.
- Empty first-run `overview` at 80 columns and compact 50 columns with all vendor
  roots isolated.
- Published-package Doctor redaction for Cursor-style encoded project paths.
- Published-package TUI demo navigation through Home, Intervals, Sessions,
  Projects, Models, Limits, Live, Forecast, Doctor, Receipt, What-If, Budgets,
  and Insights.
- Smoke artifact privacy grep for local paths, fixture IDs, session DB names, and
  encoded local path fragments.

## P2 - Data-Source Scoping Is Still Easy To Misread

Personas: HN CLI pedant, security reviewer, first-time user testing with a temp
Codex directory.

Passing `--session-root` only changes the OpenAI Codex source. Caliper still
discovers Claude Code, Cursor, and Aider from their default roots unless those
vendor roots are isolated separately.

Brutal feedback: the behavior is technically correct for a multi-vendor tool,
but the flag name invites a wrong test. A user who thinks `--session-root
/tmp/empty` means "read nothing from my machine" can still see real local usage
from other tools. That will read as a privacy bug even though it is a scoping
misunderstanding.

Status: documented as UX/docs polish, not a release blocker.

## P2 - Root Help Remains Dense

Personas: YC partner, HN drive-by installer, LinkedIn engineering manager.

The CLI has a serious command surface now. The root help is accurate, but it
still asks a cold user to scan too much before they get the first win.

Brutal feedback: the product wedge is clean; the help surface still looks like a
maintainer tool. First-run docs and launch copy need to keep steering users to
`overview`, `doctor`, and `tui --demo`.

Status: backlog.

## P2 - TUI Discoverability Is Functional, Not Effortless

Personas: Reddit first-time user, keyboard-only user, screenshot judge.

Keyboard navigation works after the `0.0.27` fixes. The remaining problem is
communication: several screens do not fully advertise the global map in the
local footer, so users learn the app through Help instead of ambient cues.

Brutal feedback: HN terminal users will tolerate this. Broader users will miss
features they cannot see.

Status: backlog.

## P2 - Repo Had Too Much Launch Archaeology

Personas: maintainer, external contributor, YC diligence reviewer.

The release history had accumulated old QA passes and pre-release TUI/persona
plans that no longer described the shipped product. That made the repo feel more
like a workbench than a clean public launch artifact.

Brutal feedback: the product is credible; the repository should not force a new
reader through stale scaffolding to understand what is current.

Status: addressed in this cleanup pass by trimming superseded QA reports and
obsolete planning docs while keeping current launch docs and the manual publish
runbook.

## Persona Attacks

### Hacker News Privacy Skeptic

"The 0.0.27 privacy behavior is finally boring in the right way. Doctor redacts
normal paths and encoded Cursor project paths. But the multi-vendor default needs
clearer language because `--session-root` is easy to misread."

### Hacker News CLI Pedant

"The CLI is powerful and mostly coherent. My remaining complaint is naming and
density, not correctness. The first-run path should be obvious without reading a
long command list."

### YC Partner

"This is launchable. The wedge is specific, the install path works, and the trust
story has been hammered. Clean the repo so diligence reads current artifacts
first."

### Reddit First-Time User

"Demo works. Empty state makes sense. The TUI is cool. I still need Help too
often, but I would not bounce."

### LinkedIn Engineering Manager

"I can forward this to senior engineers now. I want cleaner onboarding copy for a
team rollout, but the package itself no longer feels brittle."

### Finance User

"Receipts and Doctor output are safe enough to paste by default. The remaining
ask is documentation around which local tools are included in each command."

### Accessibility Reviewer

"The keyboard path survives fast navigation now. The next improvement is
discoverability: show the global shortcuts consistently without making users
memorize them."

## Good Enough?

Live `0.0.27`: yes.

No release-blocking issue was found in this pass. The cleanup work is repo hygiene
and documentation clarity, not a package hotfix.
