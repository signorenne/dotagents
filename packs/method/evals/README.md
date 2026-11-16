# Evals of the method pack

Each folder is a case for `claude plugin eval`: a prompt and free graders. No
case calls a judge model; each run is still a real Claude session, so
running them spends usage:

```sh
claude plugin eval packs/method --runs 1 --ablation none
```

`python3 tools/validate.py` checks their structure without running them.

Two kinds, by tag:

- `trigger`: `tool_used` on the Skill tool checks that the right skill fires
  and the wrong ones stay quiet. They measure whether the skills'
  descriptions alone route these requests.
- `behavior`: what a skill does once it runs, on the corrections mined from
  real sessions (14 November 2026): a source the user names is read
  (`tool_used` Read), API options are shown as code, and a final reply opens
  with `Done: yes` or `Done: no` and gives the next step as a prompt to
  paste (`regex` on the last message). They run with read-only tools and no
  fixture files, so they test replies, not edits: `--tag behavior` runs them
  alone. Not tested here: asking through the question box, since an eval
  run offers no AskUserQuestion even when a case lists it (its tools were
  Task, Glob, Grep, Read, Skill, TaskStop and ToolSearch on 14 November
  2026), and design going on into build, since design rightly stops in an
  empty workspace before any build.

The pack's session hook that prints the global rules lives in the
marketplace entry, not in this folder, so `claude plugin eval` runs without
it. Each run starts in a temporary home where nothing personal loads
(Claude Code's plugin-evals docs), so the skills `install.py` put in
`~/.claude/skills` reach neither arm. The no-plugin arm has none of these
skills, so it adds nothing here: `--ablation none` skips it and halves the
sessions.
