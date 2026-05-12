# Issue tracker: GitHub

Issues and PRDs for this repo live in GitHub Issues for `rajdeepmondaldotcom/codex-meter`.

Use the `gh` CLI or the GitHub connector for issue operations:

- Create an issue: `gh issue create --title "..." --body-file ...`
- Read an issue: `gh issue view <number> --comments`
- List issues: `gh issue list --json number,title,labels,state`
- Comment on an issue: `gh issue comment <number> --body-file ...`
- Apply labels: `gh issue edit <number> --add-label "..."`
- Close an issue: `gh issue close <number> --comment "..."`

When a skill says "publish to the issue tracker", create a GitHub issue unless the user explicitly asks for a local document instead.
