# Show HN draft

Use this verbatim or close to it. No emoji. No "we're excited." Hold until
the day of launch.

---

**Title:**
Show HN: Caliper - the cost layer for AI-assisted development (offline, no login)

**URL:** https://github.com/rajdeepmondaldotcom/caliper

**Body:**

Hi HN. I built Caliper because I had a four-figure monthly bill from
Codex, Claude Code, and Cursor and no way to point at one pull request
and say what it cost.

Caliper reads the session logs those tools already write to your disk,
joins them into one event shape, and prints per-PR, per-commit, and
per-project cost. Offline by default. No login, no SDK, no SaaS.

On my own machine, the first run produced a real number in eleven seconds:

```
Caliper - Overview
Vendors: claude-code (74,590 events) · openai-codex (20,500 events)

Last 7 days       $3,383
Last 30 days     $10,516
Last 90 days     $10,897

Events: 95,090
Cache savings: $65,871 at 99.3% cache hit
```

The wedge is the constraint: logs stay local, the only network call in
the codebase is an opt-in pricing refresh, and the privacy invariant has
a test. The trade-off is named — if a vendor never writes a log to disk,
Caliper has nothing to read.

What is in it today:

- Codex, Claude Code, Cursor, and Aider parsers.
- `caliper pr <N>`, `caliper commit <sha>`, `caliper project` for
  attribution.
- `caliper budgets check` with stable `0 / 1 / 2` exit codes for CI.
- Decimal pricing, sourced rates with `checked` dates, long-context
  multipliers per model.
- Markdown and HTML receipts. Prometheus and Grafana exports.

What it is not:

- A hosted dashboard. There is no SaaS version and none on the roadmap.
- A replacement for the vendor admin APIs. The point is to not need them.

Install:

```
uvx --isolated --from caliper-ai caliper
```

The source is short on purpose. If you do not trust the offline claim,
read `src/caliper/parser.py` end to end in one sitting.

Happy to answer questions and to be wrong in public. If you spot a
constraint I missed, please name it.

---

## Posting checklist

- [ ] PyPI release is live with the matching version.
- [ ] README install commands work on a fresh machine.
- [ ] `caliper overview` produces output on a clean checkout.
- [ ] `caliper doctor` returns 0 or 1 (not 2) on a typical setup.
- [ ] Repo description on GitHub matches the pitch line.
- [ ] First three issues on the tracker are real (not placeholders).
- [ ] No open PRs that would change the public surface in the next 24h.

## Response patterns ready to paste

**"Why not just X (some hosted tool)?"**
Caliper does the offline, per-PR slice. If you want a hosted dashboard,
those tools are better. The wedge is staying local.

**"Pricing is wrong for model Y."**
That is a rate-card issue. Pin a local rate card with
`--rate-card-file ./rates.json` to match your invoice exactly, and open
an issue with the actual numbers. The rate card carries a `checked`
date per source for this reason.

**"Does it support GitHub Copilot?"**
Not today. Copilot does not write the same kind of local session log.
Open an issue if you have a path to read the data offline.

**"Is the cache hit rate real?"**
Yes. Cached input is billed at a different rate than fresh input and
the parsers track them separately when the source exposes them.

**"Why no telemetry?"**
Because adding telemetry would make every other privacy claim in the
README a lie. The constraint is the product.
