# LinkedIn launch post

One post. Your voice. Claim, example, test, ask. Hold until the day of
launch.

---

I had a $400 month on AI coding tools and could not tell you which pull
request caused it.

Codex told me what the model did. Claude Code told me what the agent
did. Cursor told me what the IDE did. None of them told me which commit
spent the money.

So I built Caliper.

Caliper reads the session logs those tools already write to your disk,
joins them into one event shape, and prints per-PR, per-commit, and
per-project cost. Offline by default. No login. No SDK. No SaaS.

Against a sanitized local fixture, ninety days of usage, one command:

> 2,100 events. $219 spent. $640 in cache savings.

What I want from this post:

If you run a team that uses Codex, Claude Code, Cursor, or Aider, try
it on your laptop and tell me one number that surprised you. I will
use the surprises to harden the next release.

If you think a hosted version would be better than offline-first, tell
me which constraint you would relax and why. The wedge is the
constraint, so I want to hear what would change my mind.

Install:

uvx --isolated --from caliper-ai caliper

Repo: github.com/rajdeepmondaldotcom/caliper

The source is short on purpose. If you do not trust the offline claim,
read `src/caliper/parser.py` end to end in one sitting.

---

## Notes

- Numbers above are sanitized examples. Replace only with deliberately
  public-safe figures before posting.
- Do not tag any vendor. The pitch is not a comparison.
- Do not use hashtags.
- Do not paste raw local project names, session titles, or personal paths.
