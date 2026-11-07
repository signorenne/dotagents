# Contributing to <FILL: project name>

This file owns how a change gets in: the workflow, the local gates, CI, commit
messages, AI assistance, the docs format and dependencies. AGENTS.md holds the
floor for agents, and STYLE_GUIDE.md owns code style.

## Workflow

1. <FILL: the branch model the repository uses, from git log and its docs, for
   example: Branch off `main`; never commit straight to it.>
2. Write to STYLE_GUIDE.md<FILL: ; let the project's formatter and linter, by name,
   enforce it; delete this marker when the project has neither>.
3. Use agent-workflows.md in the docs folder for multi-step tasks and handoffs.
4. <FILL: the gate that must pass before a merge, with its exact command.>

## Local gates

<FILL: the git hooks or pre-commit checks, what each checks and how to enable
them, or delete this section.>

## Continuous integration

<FILL: where CI is configured and what each job checks, as a table of job and
checks.>

## Commit messages

<FILL: keep the defaults below only where the repository shows no convention of
its own (git log, existing docs); otherwise write that convention instead.>

Subject line is `type(scope): description`:

- `type` is the kind of change (table below).
- `scope` names the area: <FILL: the module or area names>.
- `description` is short, lower case, imperative, with no trailing period.

Keep the subject on one line, with no body. A change that needs more than one
sentence is split into smaller commits.

| type | for |
|---|---|
| feat | new feature or public API |
| fix | bug fix |
| perf | performance, no behavior change |
| refactor | restructuring, no feature or fix |
| test | tests only |
| docs | documentation only |
| build | build system and dependencies |
| chore | tooling and housekeeping |
| ci | CI configuration |
| style | formatting or naming only |

Do not add a `Co-Authored-By` line or any other assistant or AI trailer. One
logical change per commit.

## AI code assistants

<FILL: the project's policy on AI code assistants, only when the request or
AI_DISCLAIMER.md sets one (then: See AI_DISCLAIMER.md for the accountability
policy.); otherwise delete this marker.> Start agent work from AGENTS.md, then
use the role matrix of the docs map to load the right docs.

## Docs format

<FILL: the prose format of the docs (Markdown or Org) and its exceptions, such
as AGENTS.md and the bridges.> Register every new doc in the docs map. Prose
style, punctuation included, lives in writing.md in the docs folder.

## Dependencies

<FILL: how a new dependency is proposed and where dependencies are declared, or
delete this section.>
