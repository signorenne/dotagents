# Trigger evals of the method pack

Each folder is a case for `claude plugin eval`: a prompt and free graders
(`tool_used` on the Skill tool), which check that the right skill fires and
the wrong ones stay quiet. No case calls a judge model; each run is still a
real Claude session, so running them spends usage:

    claude plugin eval packs/method --runs 1

`python3 tools/validate.py` checks their structure without running them.
