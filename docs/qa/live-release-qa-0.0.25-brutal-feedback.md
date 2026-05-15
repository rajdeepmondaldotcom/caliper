# Caliper 0.0.25 Final Live Release QA - Brutal Feedback

Date: 2026-05-15 IST
Target: `caliper-ai==0.0.25`

## Verdict

`0.0.25` is not good enough to call the final Show HN build.

The CLI installs, the main flows run, and the TUI navigation works, but the
live package still leaked local identity in default machine-readable output.
That is a launch blocker for a tool whose wedge is offline, local-first cost
accounting.

After the fixes in this working tree, the launch blockers were closed and
published as `0.0.26`.

## What Was Tested

- PyPI metadata and isolated `uvx` install for `caliper-ai==0.0.25`.
- `pipx run --spec caliper-ai==0.0.25 caliper --version`.
- Published-package `scripts/live-release-smoke.sh`.
- Local `scripts/release-smoke.sh`.
- Default JSON redaction on overview, statusline, and rate-catalog flows.
- TUI demo navigation across Home, Intervals, Sessions, Projects, Models,
  Limits, Live, Forecast, Doctor, Receipt, What-If, Budgets, Insights, and Help.
- `NO_COLOR` theme behavior and global shortcut behavior from Help.

## P0 - Statusline JSON Leaked Local Identity

Personas: HN privacy skeptic, security reviewer, finance user wiring the prompt
line into a shared terminal screenshot.

Repro:

```sh
CALIPER_SMOKE_VERSION=0.0.25 scripts/live-release-smoke.sh
```

Then inspect the generated `statusline.json`.

Observed in the live package:

- `latest.session_id` was visible by default.
- `latest.project` included an absolute local project path.
- `top_project.label` included an absolute local project path.
- The smoke script also read external vendor data from the developer machine,
  so this was not just a synthetic fixture problem.

Brutal feedback: this is the exact failure HN will use to invalidate the whole
privacy story. A local-first cost tool cannot say "redacted by default" and then
leak paths from the prompt/statusline path. It does not matter that the normal
overview report was clean; the screenshotable one-line command is enough to
create the thread.

Status: fixed in the working tree.

## P1 - Release Smoke Was Not Hermetic

Personas: maintainer, security reviewer, YC partner asking whether the release
process is real.

The live smoke script passed `--session-root` for Codex, but it did not isolate
Claude Code, Cursor, Aider, the parse cache, or XDG data. On a real developer
machine, the smoke command silently read unrelated local usage and made the
artifact too large, too personal, and too flaky.

Brutal feedback: a release smoke test that accidentally reads the maintainer's
machine is not a release smoke test. It is a demo that only looks green because
the maintainer happens to have data.

Status: fixed in the working tree.

## P1 - `rates catalog --format json` Leaked Cache Paths

Personas: HN CLI pedant, security reviewer, user pasting JSON into an issue.

Fresh-cache `rates catalog --format json` exposed the local pricing cache path
inside both `cache_path` and the warning text.

Brutal feedback: this is smaller than leaking session paths, but it still breaks
the mental model. If default JSON is safe to paste, every local path needs to be
redacted unless the user asks for `--show-paths`.

Status: fixed in the working tree.

## P2 - TUI Navigation Is Functional But Still Under-Explained

Personas: Reddit first-time user, terminal accessibility user, LinkedIn
engineering manager judging polish from a screenshot.

The Textual app routes all tested global keys correctly, including from Help.
The problem is not functionality; it is discoverability. Several screen footers
only show local actions like refresh/back and do not remind the user that
numbered global navigation, theme, and redaction shortcuts are always available.

Brutal feedback: the TUI is usable, but it still feels like a power-user shell
more than a polished workspace. Users can learn it from `?`, but a launch-day
screenshot should not require the viewer to infer the navigation model.

Status: documented as polish backlog, not a release blocker.

## P2 - The Command Surface Is Large Enough To Intimidate Drive-By Users

Personas: HN drive-by installer, YC partner, Reddit skeptic.

`caliper --help` is accurate and complete, but it is very dense: many aliases,
many global flags, and a long command list. That is acceptable for a serious CLI,
but it weakens the first 60 seconds for someone who wants "what did this cost?"

Brutal feedback: the product is good; the help surface still makes it look more
complicated than the wedge. HN will forgive depth after the first success, not
before it.

Status: product polish backlog.

## P2 - `pipx run` Emits A Local PATH Warning In Contributor Checkouts

Personas: launch-day maintainer, docs verifier.

On this machine, `pipx run --spec caliper-ai==0.0.25 caliper --version` printed
a warning that a local `caliper` already exists on `PATH`, then ran the requested
package anyway. This is normal `pipx` behavior, not a Caliper bug.

Brutal feedback: do not paste that warning into launch evidence without context.
It reads like the install may not be clean even when it is.

Status: no code change.

## Persona Attacks

### Hacker News Privacy Skeptic

"You built the whole pitch on no upload and redaction, then your statusline JSON
leaks a local project path. I do not care that overview is clean. The promise is
global or it is not a promise."

### Hacker News CLI Pedant

"Your CLI is powerful, but the contract is uneven. Some JSON outputs are
paste-safe, others leak cache paths. Either define JSON as internal and unsafe,
or make it consistently safe."

### YC Partner

"The wedge is strong: offline cost attribution across coding tools. But the
trust boundary has to be boring. A single privacy regression turns the pitch
from 'sharp constraint' into 'maybe read the code yourself.'"

### Reddit First-Time User

"Install works. Demo works. TUI is cool. But there are too many commands and the
footer does not always tell me where I can go. I would probably use `overview`
and never discover half the app."

### LinkedIn Engineering Manager

"This is close to something I would forward to my team, but I need paste-safe
reports by default and release evidence that does not depend on the maintainer's
machine."

### Finance User

"The receipt/export story is compelling. The statusline leak is not acceptable
because finance artifacts get pasted into tickets and Slack. Safe by default has
to include every JSON path."

## Good Enough?

Live `0.0.25`: no.

Live `0.0.26`: yes. The fixed build passed the full local gate, PyPI install
checks, and the published live-release smoke.
