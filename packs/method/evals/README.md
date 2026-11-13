# Trigger evals of the method pack

Each folder is a case for `claude plugin eval`: a prompt and free graders
(`tool_used` on the Skill tool), which check that the right skill fires and
the wrong ones stay quiet. No case calls a judge model; each run is still a
real Claude session, so running them spends usage:

    claude plugin eval packs/method --runs 1

`python3 tools/validate.py` checks their structure without running them.

What a run measures: whether the skills' descriptions alone route these
requests. The pack's session hook that prints the global rules lives in
the marketplace entry, not in this folder, so `claude plugin eval` runs
without it. Run it where `install.py` has not linked the same skills into
`~/.claude/skills`, or the baseline arm finds them too and the two arms
do not separate.
