---
name: implement
description: "Implements a spec or a scoped task end to end with the project's matching workflow: grounding in the current code, plan approval, small verified steps committed one by one, a progress log of every step and of every decision with who took it (user or agent), full gates, and an independent review. Use when the user asks to implement, build or carry out a spec, a feature or a planned change in a repository."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Implement

## 1. Requirements

If given a spec path, read the whole spec; it is the source of requirements, and anything it leaves open goes to the user as a question (decide skill), not a guess. Otherwise restate the task in one line with explicit success criteria. Read the project's decision log if it has one. If a progress log for this task exists (section 5), read it before anything else: it says which steps are done and which decisions were taken. It is a map, so check it against git log and the code in step 3.

## 2. Workflow

Pick the matching workflow from the project's docs (its AGENTS.md recipes and agent workflows doc: component change, bug fix, new module, docs). Its steps and exit criteria are binding.

## 3. Ground in the current code

Unless the change fits in one sentence and one or two known files, delegate to scout. Then re-read yourself the files you will edit and the code you will call, and confirm with a search that every symbol named in the spec, the brief or a handoff still exists with the expected signature. Report any difference before planning; a renamed or missing symbol changes the plan.

## 4. Plan

List the steps. Each step is one logical change that becomes one commit, with its files and its check. Wait for the user's approval when the plan touches more than one file, changes a public API, or meets a choice that belongs to the user (use the decide skill for it). A conflict with an Accepted decision stops the work until the user resolves it.

## 5. Progress log

Once the plan is approved (or needs no approval), create the task's progress log in the project's working-notes location: .private/progress/<slug>.<ext> when .private/ is git-ignored, otherwise ask once where it goes. Use the project's progress template when it has one, in the project's prose format; the slug is the spec's slug, or the branch slug without a spec. The log is how the user reviews the work and how a later session resumes it, so keep it current as you go, not at the end:

- After each step: its status, commit hash and subject, and the check run with its result.
- Every decision taken during the work that the spec or plan did not settle, written when it is taken and marked by user or by agent. By user: what the user chose (decide skill). By agent: routine engineering choices inside the plan, with the reason and the alternative not taken, marked Review: pending so the user can keep or overturn them. When the user reviews one, record kept, or changed with the entry that replaces it.
- A decision that also meets the decision log's recording bar goes there too (Proposed unless the user accepted it), and the progress entry names its id.
- Deviations from the spec or plan, and new open questions.

Write the log from what happened (commands run, git), never from intent. It is local working notes: never commit it.

## 6. Branch

If on main or master, create a branch first: <type>/<slug>, with the type from the project's commit types.

## 7. Build each step

- Announce in one line what you will change and where, then edit. Re-read a file before editing it again after a formatter or another tool touched it.
- Behavior change: write or update the test first. Bug: make the test fail before the fix.
- Keep the project's deliverable set in sync within the step (for example header and API docs, test, example, guide, build lists, umbrella include).
- Run the narrowest check (one test binary or test case). Run short commands directly; delegate to gate-runner when output is long.
- Commit the step in the project's convention, unless the user said not to commit.
- Update the progress log (section 5) before starting the next step.

## 8. Gates

When all steps are in, delegate to gate-runner for the project's full pre-PR gates. Fix failures in the code, never by weakening a gate.

## 9. Review

Delegate to reviewer with the intent of the change. Fix blocker and major findings, rerun the affected gates, and when a fix changed behavior, delegate one more reviewer pass limited to the fix. Report minor findings you chose not to fix, with the reason.

## 10. Report

Use the project's handoff format when it has one (Goal, Files touched, Decisions, Open questions, Commands run, Commands still needed, Risks), plus the commit list and the path of the progress log. List the decisions by agent still marked Review: pending, one line each, so the user can review them in one place. Never push.

After two failed attempts at the same problem, stop, restate assumptions and evidence, and propose a different approach before trying again. Use the systematic-debugging skill if it is available.
