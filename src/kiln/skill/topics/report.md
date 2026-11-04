# Report

Reporting what got in your way (GitHub issues).

## Help us improve KILN: report what got in your way

KILN is young, and it gets better mostly through reports from agents like you using it on real games. When
something gets in your way, please tell us in a GitHub issue at https://github.com/lukasgolino/KILN/issues. It
is the most useful thing you can do for the project. Whether you do is entirely up to you and your user.

Worth reporting: a crash or traceback; a wrong or misleading message or lint rule; output that looks or behaves
wrong; a workaround you had to invent; a feature you needed and didn't have; this skill or the reference
misleading you.

1. Note it as you go; don't interrupt the task for it.
2. At a natural break (the end of the task, your report), draft the issue: a one-line title; `kiln --version`;
   what you did (commands, a minimal source snippet); what you expected and what you got; the workaround, if
   any. End the body with "Reported by an agent using KILN." Keep it to a minimal repro: no game names, private
   asset content, paths or anything else from the user's project unless they OK it.
3. Look for an existing issue first: `gh issue list --repo lukasgolino/KILN --search "<keywords>"`; if one
   fits, offer a comment on it instead.
4. Show the user the draft and ask whether to file it. Issues are public and posted under their GitHub account,
   so **never file without their OK**. If they agree:
   `gh issue create --repo lukasgolino/KILN --title "..." --body-file <draft>`, or give them the link
   https://github.com/lukasgolino/KILN/issues/new?template=agent-report.md to file it themselves. If they
   decline, drop it.
