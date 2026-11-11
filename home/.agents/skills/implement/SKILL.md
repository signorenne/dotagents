---
name: implement
description: "Implements a spec or a scoped task end to end with the project's matching workflow: grounding in the current code, plan approval, small verified steps committed one by one, a progress log of every step and of every decision with who took it (user or agent), full gates, and an independent review. Use when the user asks to implement, build or carry out a spec, a feature or a planned change in a repository. Not for a one-sentence change (do it directly) or a cross-module feature with no spec yet (spec first)."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Implement

## 1. Requirements

If a progress log for this task exists (section 5), read it first: it says which steps are done and which decisions were taken, and it is a map, so check it against git log and the code in step 3. If given a spec path, read the whole spec; it is the source of requirements. Anything it leaves open that belongs to the user (scope, public API, architecture, trade-offs) goes to the user (decide skill), not a guess; routine engineering choices are yours and go in the progress log as by agent. Without a spec, restate the task in one line with explicit success criteria. Read the project's decision log if it has one.

## 2. Workflow

Pick the matching workflow from the project's docs (its AGENTS.md recipes and agent workflows doc). Its steps and exit criteria are binding and add to this skill's steps; where they conflict, the project's workflow wins. When none matches, follow this skill's steps.

## 3. Ground in the current code

Unless the change fits in one sentence and one or two known files, delegate to scout. Then re-read yourself the files you will edit and the code you will call, and confirm with a search that every symbol named in the spec, the brief or a handoff still exists with the expected signature. Report any difference before planning; a renamed or missing symbol changes the plan.

## 4. Plan

List the steps. Each step is one logical change that becomes one commit, with its files and its check. Name the assumptions the plan rests on that would change it if they were wrong (how a symbol behaves, a tool's limit, a fact from the docs), each with the check that could refute it, and run each check before the step that depends on it. Wait for the user's approval when the plan touches more than one file, changes a public API, or meets a choice that belongs to the user (use the decide skill for it). A conflict with an Accepted decision stops the work until the user resolves it.

## 5. Progress log

Once the plan is approved (or needs no approval), create the task's progress log in the project's working-notes location: .private/progress/<slug>.<ext> when .private/ is git-ignored, otherwise ask once where it goes. Use the project's progress template when it has one, in the project's prose format; the slug is the spec's slug, or without a spec a short kebab-case name of the task, also used for the branch in section 6. The log is how the user reviews the work and how a later session resumes it, so keep it current as you go, not at the end:

- Before editing for a step: set its status to in progress with the files it will change. A later session that finds a step in progress with no matching commit shows the diff of those files and asks the user whether to finish or discard it; it discards nothing without that answer. When the user said not to commit, a finished step is done with "not committed" in place of the hash.
- After each step: its status, commit hash and subject, the check run with its result, and for each behavior a new or changed test pins, the run that showed its test failing first (none for a test only moved or renamed).
- Every decision taken during the work that the spec or plan did not settle, written when it is taken and marked by user or by agent. By user: what the user chose (decide skill). By agent: routine engineering choices inside the plan, with the reason and the alternative not taken, marked Review: pending so the user can keep or overturn them. When the user reviews one, record kept, or changed with the entry that replaces it.
- A decision that also meets the decision log's recording bar goes there too (Proposed unless the user accepted it), and the progress entry names its id.
- Deviations from the spec or plan, and new open questions.
- Each refuted assumption, when its check breaks it: what was assumed, the check that broke it, what changed.

Write the log from what happened (commands run, git), never from intent. It is local working notes: never commit it.

## 6. Branch

If on main or master, create a branch first: <type>/<slug>, with the type from the project's commit types.

## 7. Build each step

- Re-read a file before editing it again after a formatter or another tool touched it.
- Behavior change: write or update the test first, following the trustworthy-tests skill if it is available, and see it fail for the right reason before writing the code that makes it pass. Bug: make the test fail on the unfixed code before the fix. Change an existing test's expected value only with the evidence the global rules require; a failing test that could pass only by being deleted, skipped or loosened is a question for the user, not an edit, except deleting the test of a behavior the approved spec or plan removes.
- Never edit a generated file (marked as generated, or written by a build step): change its generator or input and regenerate, committing both when the output is tracked; check that regenerating from unchanged input gives no diff, and if the generator is missing, stop and report. The exceptions are generators that keep hand edits in marked regions, and one-off scaffolding the project now owns.
- Keep the project's deliverable set in sync within the step (for example header and API docs, test, example, guide, build lists, umbrella include).
- Run the narrowest check (one test binary or test case). Run short commands directly; delegate to gate-runner when output is long.
- Commit the step in the project's convention, unless the user said not to commit. Where the sandbox blocks git commit (Codex by default), ask for approval, or leave the step uncommitted and log it as not committed.
- Update the progress log (section 5) before starting the next step.

## 8. Gates

When all steps are in, delegate to gate-runner for the project's full pre-PR gates. Fix failures in the code, never by weakening a gate or a test; correcting an expected value that the evidence proves wrong is not weakening, and the progress log cites that evidence. An INCOMPLETE gate has not passed: never report the work as done while one stands; list it with its log path among the commands still to run (Commands still needed in the handoff format).

## 9. Review

Delegate to reviewer with the intent of the change, the progress log path, and the branch's base commit when it is not main. Fix blocker and major findings; when a fix changed behavior, delegate one more reviewer pass limited to the fix. When a fix landed, run the full gates again on the final commit, the HEAD after every fix: the work is done only when they pass there. Report minor findings you chose not to fix, with the reason.

## 10. Report

Use the project's handoff format when it has one (Goal, Files touched, Decisions, Open questions, Commands run, Commands still needed, Risks, Refuted assumptions, Verify before use), plus the commit list, the final commit's hash with its gate results, and the path of the progress log. List the decisions by agent still marked Review: pending, one line each, so the user can review them in one place. Never push.

After two failed attempts at the same problem, use the systematic-debugging skill if it is available.
