# Pitch lock

Source of truth for every user-facing word in Caliper. README, PyPI, CLI help,
docs site, launch posts, error messages. If a sentence ships and it does not
match this doc, this doc wins.

Locked on 2026-05-13. Owner: Rajdeep.

## The pitch

> **The cost layer for AI-assisted development.**
>
> Reads local Codex, Claude Code, Cursor, and Aider logs. Prints what each
> PR cost. Offline. No login.

Two lines. Headline stakes the category. Subtitle names the input (local
vendor logs), the output (per-PR cost), and the constraint (offline, no
login).

A YC partner who reads only the headline knows the category slot. An HN
engineer who reads both lines knows the user, the wedge, and the product edge in
one skim.

If we ever have to drop one line, drop the subtitle and keep the headline.
The category line carries the pitch alone.

## The three sub-claims everything else inherits

1. **The data is already on your disk.** Codex, Claude Code, Cursor, and Aider
   write session logs locally. Caliper reads those logs. There is nothing to
   instrument, no API to wire, no daemon to run.
2. **The unit of value is a receipt.** Not a dashboard. Not a leaderboard. A
   per-PR, per-commit, per-session receipt that you can paste into a standup
   or a CFO email and defend.
3. **Local stays local.** No login, no upload, no telemetry. The only network
   call is an opt-in pricing refresh behind a flag. This is a constraint, not
   a marketing line. It is enforced in tests.

Every paragraph in every surface should be traceable to one of those three.
If it is not, it is decoration.

## The receipt is the demo

The 30-second proof block in the README and docs landing is one rendered
PR receipt. Not a feature list. The receipt is the argument.

Use real numbers from `caliper overview` and `caliper pr` runs on this
machine, redacted where they reference private repos or session titles.

Reference figures captured 2026-05-13 from this machine:

- 95,090 events parsed across 90 days.
- 4 vendors detected: Claude Code, OpenAI Codex, Cursor, Aider.
- $10,897.56 estimated API spend.
- $65,871.47 cache savings detected at 99.3% cache hit.
- 1,968 models in the pricing catalog.
- 1 command to produce the above: `caliper overview`.

The numbers carry the pitch better than any adjective. Use them.

## Audience priority

1. **HN engineer.** Skims the README on a phone, decides in 60 seconds. If they
   star, they ship to their team channel. The first paragraph and the proof
   block are for them.
2. **Engineering manager with an AI budget.** Reads the budgets and per-PR
   sections. Cares about a number they can quote.
3. **YC partner or investor.** Reads the same README and decides if the wedge
   is real. Served by the same constraint-first writing that serves the
   engineer. No separate "investor" surface.

Do not write for all three at once. Write for the engineer. The other two
inherit the trust.

## Banned, on sight

Pulled directly from the voice profile. If any of these appear in a draft,
cut them or rewrite the sentence:

- "leverage", "unlock", "empower", "drive", "enable", "deliver", "execute"
- "thrilled", "excited", "delighted", "proud to announce", "journey"
- "game-changing", "revolutionary", "cutting-edge", "next-gen", "world-class"
- "best-in-class", "enterprise-grade", "AI-powered", "ML-driven"
- "obviously", "simply", "just", "basically", "actually"
- em dashes
- semicolons in user-facing copy
- exclamation points outside code blocks
- emoji in CLI output and docs prose

If a draft sounds smooth in three sentences, suspect it. Read it out loud
before commit.

## Structural rule for every surface

The five-line shape, in order:

1. **The claim.** One sentence the reader could disagree with.
2. **The anchor.** A real command, a real output, or a real number.
3. **The constraint.** What this does not do, or what it costs to use.
4. **The trade-off.** What you give up, named, not hidden.
5. **The next move.** One command, one link, one decision.

Surfaces shorter than five paragraphs collapse multiple lines into one, but
keep the order. The constraint and the next move never get cut.

## Who Caliper is for, in one line each

- **Indie developers paying their own AI bill.** You see the credit card
  charge. You want the line items.
- **Engineering managers running AI-heavy teams.** You want a number per PR
  that you can take to a budget meeting.
- **Anyone with a strict data policy.** Logs stay on disk. You can read every
  line of the parser before you trust it.

## Who Caliper is not for

- Teams that want a hosted dashboard with sign-in. There are products for
  that. Caliper is not one.
- Teams that have not adopted Codex, Claude Code, Cursor, or Aider. There is
  nothing on disk to read.

Naming the non-user is part of the pitch. Do not soften it.

## The FAQ a HN commenter will write before reading the code

These get answered in the README, in this order, in one paragraph each:

1. Does it work with Cursor today? (Yes for sessions, with the documented
   caveat that some Cursor files do not carry per-event token counts.)
2. Why not just read the vendor dashboards? (Because the dashboards are
   per-vendor, not per-PR, and they require a login.)
3. How accurate are the costs? (As accurate as the rate card. The rate card
   ships with a checked-on date and `doctor` warns when it gets old.)
4. What about the Anthropic admin API or the OpenAI usage API? (Out of scope.
   Caliper is local-only by design. The trade-off is named in the pitch.)
5. Can I self-host the export? (Yes. The Prometheus and Grafana exporters
   are local processes.)

## Decision template for every commit on this work

Before merging a messaging change, the diff has to clear three bars:

- The first sentence is a claim, not a label.
- Every number in the diff was produced by a real command on this machine.
- A reader can paste one command from the diff and reach the next move.

If any bar fails, the change goes back.
