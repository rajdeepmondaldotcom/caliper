# Objections to expect on launch day

Internal use. Every objection I can predict from HN and YC reviewers,
with the honest answer. Some of these became FAQ entries in the README.
The rest live here so we are not surprised in real time.

## On the wedge

**"This is a feature, not a product."**
Today, yes. The bet is that local-first cost attribution is a wedge into
two things people pay for: budget gating in CI and per-team cost
allocation. Both are downstream of one event shape.

**"Why not just sell a hosted dashboard?"**
Because the moment Caliper requires a login, every privacy claim in the
README becomes a lie, and the contributor base that trusts the project
walks. The hosted business is a different company. This one is not it.

**"This will be table stakes when OpenAI ships per-PR billing."**
Maybe. Two things stay true: the vendors do not control your git history,
and they will never tell you what Cursor and Claude cost from inside
one report. The cross-vendor join is the moat.

## On accuracy

**"The cost is wrong for model X."**
Pin a local rate card with `--rate-card-file ./rates.json`. Open an
issue with the invoice line item and the model name. The rate card
carries a `checked` date for every source URL so we can tell when it
went stale.

**"You are guessing the service tier."**
Yes, with a documented precedence chain. The default tier is recorded
on every event so JSON output and `doctor` show how many events came
from each source. Pass `--tier-overrides` to fix it.

**"Cache hit rates look too high."**
They are real. Cached input is billed at a different rate than fresh
input. The 99.3% number on a Claude-heavy day is plausible because the
vendor caches the context aggressively. If you do not believe it,
inspect `caliper evidence`.

## On security and privacy

**"You are reading my prompts."**
The parser reads the file, but prompt text never reaches a
`UsageEvent`. Redaction is on by default. The privacy invariant has a
test. If you do not trust it, `src/caliper/parser.py` is short.

**"What if you ship telemetry later?"**
The CONTRIBUTING file says we will respectfully decline any PR that
adds telemetry. That is a public commitment, not a hope.

**"What if a malicious dependency gets pulled in?"**
The runtime dependency list is `rich`, `typer`, `platformdirs`, plus an
optional `prometheus-client` extra. Adding anything else requires a
real reason. Dependabot is on.

## On positioning

**"This is just ccusage / per-vendor scripts."**
Per-vendor scripts answer per-vendor questions. Caliper answers
cross-vendor questions. The unit of value is the PR, not the model.

**"YC-ready language? Why not just ship?"**
We did ship. The messaging rewrite exists because the code shipped
faster than the words. The README claim has to match what the binary
does on a clean machine.

**"2k stars in a week is a vanity metric."**
Yes. The reason we track it is not the number. It is the signal that
the pitch is legible enough that an engineer can repeat it after a
single skim. If the pitch is legible, the tool gets adopted. The stars
are the proxy.

## On scope

**"Where is GitHub Copilot?"**
Copilot does not write the same kind of local session log. If you have
a path to read its data offline, open an issue. We will not add it via
a sign-in flow.

**"Where is the team mode?"**
Today: each developer runs Caliper locally and exports a receipt the
team can read. Tomorrow: a thin shared rate-card and budget file in
git. Hosted: not on the roadmap.

**"Will you support per-repo budgets?"**
Yes, the next feature on the list. The data model already groups by
project. The budget table needs a per-project key.

## On business

**"How do you monetize?"**
Not today. The library and the CLI stay MIT. If a paid surface lands
later, it is a team-mode artifact (shared budgets, shared rate cards,
audit trails) that sits on top of the same offline core. The free tier
stays full.

**"Is this YC-ready?"**
The answer YC wants is a real user, a real number, and a constraint
nobody else is willing to keep. Caliper has all three. The
rest is execution.
