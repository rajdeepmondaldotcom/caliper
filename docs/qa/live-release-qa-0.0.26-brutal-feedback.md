# Caliper 0.0.26 Final Live Release QA - Brutal Feedback

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.26`

## Verdict

`0.0.26` is not the final build I would put in front of Hacker News.

The package installs cleanly, the main CLI smoke tests pass, the first-run empty
state is humane, and the default overview/statusline/rates JSON privacy fixes
from `0.0.26` hold. But final-release QA found two launch-grade polish problems:

- `caliper doctor` still exposed local diagnostic paths by default in human,
  JSON, Markdown, and CSV output.
- Rapid TUI navigation could trigger a Textual header callback race, and the
  What-If input could block global navigation while focused.

Those are not catastrophic product failures, but they are exactly the kind of
"almost polished" defects that turn a Show HN thread from product discussion
into implementation nitpicking.

Status: fixed in the working tree for the next release.

## What Was Tested

- PyPI metadata for `caliper-ai==0.0.26`.
- `uvx --isolated --refresh --from caliper-ai==0.0.26 caliper --version`.
- `pipx run --spec caliper-ai==0.0.26 caliper --version`.
- Published-package `CALIPER_SMOKE_VERSION=0.0.26 scripts/live-release-smoke.sh`.
- Empty first-run `overview` human and JSON output.
- Narrow `overview --compact --width 50` output.
- Default redaction in smoke artifacts, including statusline and rates catalog.
- Published TUI launch via `caliper tui --demo --no-watchdog`.
- TUI automated navigation across Home, Intervals, Sessions, Projects, Models,
  Limits, Live, Forecast, Doctor, Receipt, What-If, Budgets, Insights, and Help.

## P1 - Doctor Still Leaked Local Diagnostic Paths

Personas: HN privacy skeptic, security reviewer, user pasting diagnostic output
into GitHub, finance operator sharing a terminal screenshot.

The published `0.0.26` Doctor command redacted paths in the TUI, but the CLI
Doctor still printed diagnostic paths by default. This included the session root,
state DB, vendor roots, warning example paths, and Cursor project directories
where local paths can be encoded into a single folder name.

Brutal feedback: this breaks the product's trust story at the worst possible
place. `doctor` is the command people run when asking for help. If the safe
support command leaks local paths by default, the "offline and redacted by
default" claim becomes conditional and fragile.

Expected contract:

- Default Doctor output should be safe to paste.
- `--show-paths` should be the only path reveal switch.
- The contract should hold for table, JSON, Markdown, and CSV.
- Redaction should catch both normal absolute paths and vendor-encoded path
  fragments.

Status: fixed in the working tree.

## P1 - TUI Header Race Under Fast Navigation

Personas: HN terminal nerd, Reddit power user, accessibility tester using quick
keyboard-only navigation.

The published app could launch interactively, but automated TUI navigation
surfaced a Textual `HeaderTitle` race when moving quickly between secondary
screens. The built-in Textual `Header` schedules a delayed title update; after a
screen is popped, that callback can run against a header whose title child is
already gone.

Brutal feedback: "It works if I drive slowly" is not a launch-quality TUI answer.
Users mash keys. Test pilots mash keys. Reviewers mash keys. A terminal app that
crashes or logs internal widget tracebacks during keyboard navigation feels like
a prototype, even if the data layer is solid.

Status: fixed in the working tree with a Caliper-owned stable header widget.

## P1 - What-If Input Could Trap Global Navigation

Personas: spreadsheet-minded finance user, keyboard-only user, HN CLI pedant.

The What-If screen intentionally contains text inputs. When an empty input had
focus, global single-key navigation needed to keep working. The old handler tried
to perform app navigation while the input event was still active, which could
deadlock screen teardown.

Brutal feedback: the most advanced screen should not be the one where keyboard
navigation becomes least reliable. If the footer and help imply global shortcuts,
they must work from focused inputs too.

Status: fixed in the working tree by scheduling app navigation after the input
handler returns.

## P2 - CLI Help Is Accurate But Still Overwhelming

Personas: drive-by HN installer, YC partner with 90 seconds, LinkedIn manager
forwarding a tool to a team.

`caliper --help` is complete, but it is dense: many subcommands, aliases, and
global flags. Serious users will appreciate the surface area later. First-time
users want one obvious win.

Brutal feedback: the first minute should scream "run overview or demo." The
current help output is correct but still reads like a mature internal tool.

Status: backlog, not a release blocker.

## P2 - TUI Footer Discoverability Is Better Than Before, Not Perfect

Personas: Reddit first-time user, terminal accessibility user, screenshot judge.

Global navigation works after the fixes, but some secondary footers still focus
on local actions and do not fully advertise the global map. Help is available,
but launch-day screenshots need to communicate navigability without requiring a
manual.

Brutal feedback: the TUI is usable and much more polished than earlier builds,
but it still has some "power user shell" residue. For HN, that is acceptable; for
a broader non-terminal audience, it is not done.

Status: backlog, not a release blocker.

## P2 - `pipx run` Warning Can Confuse Release Evidence

Personas: launch maintainer, docs verifier.

On this contributor machine, `pipx run --spec caliper-ai==0.0.26 caliper
--version` printed the normal `pipx` warning that a local `caliper` command
already exists on `PATH`, then ran the requested package.

Brutal feedback: do not paste raw release evidence that looks ambiguous. People
will assume the wrong executable ran even when `pipx` did the right thing.

Status: no code change.

## Persona Attacks

### Hacker News Privacy Skeptic

"You closed the statusline leak, then left Doctor leaking paths. Doctor is the
support command. That is where people paste output. Privacy by default cannot be
per-command folklore."

### Hacker News Terminal Pedant

"The TUI is ambitious and mostly nice, but a HeaderTitle traceback during fast
navigation makes it feel like you shipped a demo against a moving widget library.
Own the chrome or pin the behavior."

### YC Partner

"The wedge is still strong: local multi-tool AI cost accounting. But the launch
claim is trust. Every default output must be paste-safe, and every demo path must
survive impatient usage."

### Reddit First-Time User

"Install works. Demo mode works. Empty state tells me what happened. But if I hit
keys quickly and see an internal traceback, I am out. I do not debug launch demos."

### LinkedIn Engineering Manager

"I can forward this to senior engineers after the path leak and TUI race are
fixed. Before that, it looks like a promising beta with a support-risk footgun."

### Finance User

"Doctor output will end up in tickets. Cost reports will end up in Slack. Default
redaction needs to apply everywhere, not only the commands you expect me to use."

### Accessibility Reviewer

"Keyboard navigation is the whole TUI. If a focused input changes the shortcut
contract or blocks navigation, that is not an edge case. That is the interface."

## Good Enough?

Live `0.0.26`: no.

Live `0.0.27`: yes. The fixed build passed the full local gate, package smoke
checks, PyPI install checks, live Doctor encoded-path redaction probe, and live
TUI navigation probe.
