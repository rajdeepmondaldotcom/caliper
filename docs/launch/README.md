# docs/launch

Drafts for the public launch. Committed for version control, not for
publishing. Nothing in this folder is consumed by the build or the docs
site.

| File | What it is |
| --- | --- |
| [hn-show.md](hn-show.md) | Show HN post draft, posting checklist, response patterns. |
| [tweet-launch.md](tweet-launch.md) | Three tweet variants. Pick one for launch day. |
| [linkedin-launch.md](linkedin-launch.md) | LinkedIn post in Rajdeep's voice. |
| [faq-objections.md](faq-objections.md) | Every objection to expect, with the honest answer. Internal. |

## When to publish

Before launch:

- [ ] Re-run `caliper overview` and confirm the numbers in the drafts
      match.
- [ ] Confirm the GitHub repo description and PyPI description match
      the pitch line in `docs/messaging/PITCH.md`.
- [ ] Confirm `uvx --from caliper-ai caliper` works on a fresh machine.

On launch day:

1. Publish Show HN first. Watch the first hour.
2. Tweet (variant 1 by default).
3. Post LinkedIn within the same hour.
4. Stay in the thread. Answer with the patterns in `hn-show.md` if the
   objection matches one already prepared.

After 48 hours:

- Move the surviving FAQ items from `faq-objections.md` into the README
  FAQ. Delete the items that no one asked.
