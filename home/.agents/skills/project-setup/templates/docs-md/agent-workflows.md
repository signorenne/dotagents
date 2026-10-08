# Agent workflows

Owns the reusable multi-step workflows for AI agents and human contributors.
AGENTS.md carries the short working-memory floor; this file carries the
playbooks.

## Common sequence

1. Scout: read the docs the task needs, inspect the touched area, identify
   owners, nearby tests and examples, risks, existing components worth reusing,
   and the Accepted decisions that constrain the task.
2. Plan: choose files, steps, validation commands, and the smallest coherent
   scope. Each step becomes one commit.
3. Implement: re-read the code before each edit, then change code, tests,
   examples and docs together.
4. Review: inspect the diff for behavior, missing coverage, drift, and commands
   that still need to run.

## Spec workflow

Use this before a new module, a public component with open design choices, or
any change that spans modules. Skip it when the diff fits in one sentence.

1. Scout the area, including the decision log.
2. Settle each open design choice with the maintainer, one question at a time,
   with a recommended option and the consequence of each option. Ask only what
   no owning doc or Accepted decision settles.
3. Write a self-contained implementation spec to .private/specs/<slug>.md with
   the sections below. A reader without access to the discussion must be able
   to implement it: name files, types, functions, error behavior and commands.
4. Record each new decision that meets the bar in the decision log's "When to
   record", following its authority rules.
5. Stop. Implement from the spec in a fresh session in the same checkout.
   .private/ is untracked, so the spec does not follow into a new worktree or
   clone; pass it by absolute path there.

```text
Objective:
Non-goals:
Affected areas and dependency constraints:
Public surface (types, functions, error model):
Reuse (existing components composed or extended):
Behavior and edge cases:
Deliverables (tests, examples, docs, build wiring):
Decisions (Accepted ids relied on, new ones proposed):
Acceptance criteria:
Verification commands:
Open questions:
```

## Component change workflow

<FILL: the project's recipe for adding or changing a public component: which
files travel together (code, API docs, tests, example, guide, build lists) and
the exit criteria.>

## Bug fix workflow

1. Reproduce the bug with the narrowest test or example.
2. Add a failing test when the bug affects public behavior.
3. Fix the implementation without weakening the test.
4. Update docs only when the documented behavior changes or the docs made the
   bug likely.
5. Run the fixed test, then the module suite, then the wider gates the risk
   calls for.

## Review workflow

Review starts with findings, not summary. Check behavior and edge cases, calls
to symbols that no longer exist, missing tests or examples, docs drift, build
wiring, dependency policy, conflicts with Accepted decisions, and validation
commands that were skipped. When there are no findings, say so and name the
residual risk.

## Parallel work

Parallel work helps only when scopes do not touch the same files. Use separate
git worktrees for parallel implementation, with one merge owner who integrates,
resolves conflicts and runs the wider validation.

## Handoff template

```text
Goal:
Files touched:
Decisions (log id and status):
Open questions:
Commands run:
Commands still needed:
Risks:
Verify before use (files and symbols the next session depends on):
```

A handoff that must outlive the session goes to
.private/handoff/<date>-<slug>.md. Missing commands are never fine.
