---
name: build
description: "Builds one change in a repository end to end: investigates, picks the lane (direct, quick or full) and says it, writes the plan file, asks once when the lane needs approval, builds step by step with each check logged by script, triages the review, and leaves a plan file any later session resumes from. Use when the user asks to implement, build, fix, change, refactor or carry out a feature, task, plan or spec in a repository, or to resume or continue such work. Not for work that needs several plans (design first) or a review alone (branch-review)."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne). See LICENSE.txt"
---

# Build

This skill applies the method (defined in METHOD.org of the dotagents repository) and holds what an agent needs to follow it. Scripts: S is this skill's scripts folder, in Claude Code ${CLAUDE_SKILL_DIR}/scripts, elsewhere ~/.agents/skills/build/scripts. Each runs with python3 and prints a short result. check_step.py runs the words after -- as one program with its arguments: a command that holds a shell operator (&&, a pipe, a redirection) or a leading VAR=value goes after -- as one quoted argument, which runs through the shell.

## 0. Resume

Run python3 $S/plan_state.py first. On a task branch with a plan file it prints the header, the step in progress and the open rulings: continue from Next, keeping an approved plan approved unless the code it maps has changed in a way that changes it; in the full lane run the baseline again on HEAD before the next step, as check_step --step resume --baseline (the base's line stays the one to compare with). A step in progress with no commit: show the diff of its files and ask whether to finish or discard it; discard nothing without the answer. Off a task branch it lists the open plans.

## 1. Investigate, asking nothing

- Read the project's instructions, its workflow for this kind of change (it wins where it conflicts with this skill) and its decision log; the accepted entries bind.
- Starting intent: the user's request, a design's plan entry, or an older spec, progress log or handoff, read whole. A rule change given there with its exact text was approved: apply it as written.
- Map the code yourself when the area is known and small; delegate to scout (return: its standard brief, at most 60 lines) only when it is unknown or wide. A code map (or a design) records the commit it was checked on; while git diff --quiet <that commit> HEAD -- <its paths> exits 0, it still holds.
- Re-read every file you will edit and the code you will call; confirm each symbol with a search.

## 2. Choose the lane and say it

One line: the lane, the risk grade (low, medium, high) and why, so the user can override in one word. The user can also pin the review: "no review" (recorded in Intent; floor_check and the gates still run) or "thorough review" (full mode and a second pass on the fixes, whatever the lane). Direct: one sentence, one or two known files. Quick: about 100 changed lines or fewer, no risk surface, no choice that is the user's. Full: anything larger, or any risk surface (public API, data migration, security, new dependency, threading, the build, an irreversible step). A lane is raised mid-work when the work proves larger, never lowered. Work that needs several plans: stop here and propose a design (design skill).

Direct lane: say in one line the check that shows it done, make the change, run that check, re-read the diff, report what changed and the check's result. No plan file. Sections 3 to 7 do not apply.

## 3. Write the plan

Path: .private/plans/<slug>.<ext> in the project's prose format; slug in kebab case, also the branch's. In a linked worktree (git rev-parse --path-format=absolute --git-dir --git-common-dir prints two different paths) use the main checkout's .private/ by absolute path and never create one in the worktree. When .private/ is not git-ignored, ask once where plans go. Write the plan from what happened, never from intent, and never commit it.

```
#+TITLE: Plan: <change>

- Status: draft
- Lane: full
- Risk: medium
- Base: <short hash of the base commit>
- Branch: <type>/<slug>
- Review: full
- Next: <one line>

* Intent
* Code map
* Assumptions
| Nr | Assumption | Check | Result |
* Steps
| Nr | Step | Files | Check | Status | Commit |
* Verification
* Rulings
| Nr | Ruling | Why | Alternative | Cost if wrong | Review |
* Dead ends
* Review
| Nr | Source | Severity | Location | Finding | Verdict | Evidence |
```

In markdown the title is "# Plan: <change>" and each section a "## " heading; tables stay the same. A pipe inside a table cell is written \| in markdown and \vert in org. The quick lane writes the header, a short Intent with its acceptance criteria, the Steps table and Verification, and adds Rulings, Dead ends or Review when their first row comes.

- Intent, frozen at approval: the problem, the approach, what must always hold, what is out of scope, the acceptance criteria as observable behaviors a test or command can fail, observed where the effect is consumed, and the unchanged behavior as WHEN <condition> the system SHALL CONTINUE TO <behavior>, each with the test that pins it (path and name). Self-contained: no "as discussed". Compared measurements come from one session with known spread.
- Code map: the commit it was checked on, then exact files, symbols and lines, what to reuse, what not to touch. For each function or mechanism a step relies on, its early returns, guards, preconditions and the code that runs before it (initialization, registration), and why the step's effect happens, with file:line.
- Assumptions: each one the plan rests on, with the cheapest check that could refute it; run each before the step that depends on it and record the result.
- Steps: one logical change and one commit each, with files and the narrow check. Then the constraints that hold for every step, and for dependent steps the exact interface one produces and the other consumes. A step that changes a value searches the tests for it and its derived values; its failing test must fail at run time, not stop the build. A destructive or safety decision uses the code's own conservative predicate when one exists.
- Verification: the narrow check per step (seconds or minutes) and the project's full gates, run once on the last commit.

Full lane: before showing the plan, have an agent that did not write it check it (general subagent told not to edit; elsewhere the reviewer told the target is the plan file; return: findings, at most 40 lines): first, from the plan alone and before opening any other file, it writes what the plan proposes and how the code works according to it; a wrong or impossible paraphrase is a finding. Then it checks every file, symbol, command and fact the plan names against the code and the installed tools, applies the rules of the Code map and Steps bullets above (mechanisms with file:line, values searched in the tests, failing tests that fail at run time, conservative predicates), names each criterion no test could fail, and gives a second reading for any criterion that has one. Fix the plan; a criterion with two readings becomes a question.

Then one message: the lane, the plan path and the assumptions as a table (evidence, what breaks if wrong, how sure); then ask the open questions that are the user's through the tool's question interface when it has one (in Claude Code AskUserQuestion), among them, for high risk or parallel work, whether to run it through isolated-work: one question per item, its options with their consequences and the recommended one first, at most four per call and more in further calls, a dependent question after the answer it depends on (decide skill for a hard one); without the interface, a numbered list in the same message. With no open question, the one question is whether to approve the plan as shown. The answers approve it: record who approved and when, and the answer on isolated-work, in Intent and set Status approved. Quick lane: announce the plan in a few lines and go on without waiting.

## 4. Branch and baseline

Branch <type>/<slug> with the project's commit types; never work on main. When the answer recorded in Intent took isolated-work (section 3), create the branch in its own worktree instead (isolated-work section 1). Decision-log entries the design added and did not commit are the branch's first commit. Full lane: before step 1 run python3 $S/check_step.py --step base --baseline -- <narrow check plus the tests of the unchanged behavior> on the base; a failure predates the work: report it, never fix it silently. Set Status in progress.

## 5. Build each step

- Set its row to in progress with its files before editing; re-read a file a formatter touched before editing it again.
- Behavior change: write the test first and see it fail for the right reason with python3 $S/check_step.py --step <nr> --expect-fail -- <test>; for a bug, on the unfixed code; for unchanged behavior, break it on purpose, see the test fail, undo (trustworthy-tests). Then the code, then python3 $S/check_step.py --step <nr> -- <narrow check>. When the check passes and the step's deliverable set (next bullets) is in sync, the step is done: no polish, refactor or edit beyond its planned files and deliverables; anything worth more is a deferred line or a ruling for a later plan. Long output goes through gate-runner (return: verdict table and first errors) with the folder and the expected commit.
- Never edit a generated file: change its generator or input, regenerate, commit both, and check that regenerating from unchanged input gives no diff. Generator missing: stop (an architecture the plan does not hold). The exceptions: generators that keep hand edits in marked regions, and one-off scaffolding the project now owns.
- Keep the deliverable set in sync in the same step (docs, tests, examples, build lists); a new build or test command joins the project's documented validation commands. After removing or renaming a file or folder, search for its path, not only its name, and run every test module that names it; a change to a file that a size or format test reads runs that test too.
- Commit the step in the project's convention, one commit per step, or one for steps whose files overlap. When the user said not to commit, mark the row "not committed"; where the sandbox blocks commits, ask, or mark it "not committed (sandbox)". Set the row done with its commit. The step-log hook, or the next check_step call, records the commit in the log; never write facts a command can record.
- A request the user adds mid-work goes into Intent when the plan covers it, otherwise one line in .private/deferred.<ext>; the final reply gives its state.
- A choice the plan did not settle: a ruling row (reason, alternative, cost if wrong, Review pending), and go on; one that meets the decision log's recording bar is also drafted there as Proposed. An approach that failed: one Dead ends line. A refuted assumption: its Result cell, and the plan or a ruling changes with it. Stop only for the global rules' stop list; write the stop in Next with Status blocked. A problem outside this change: one line in .private/deferred.<ext>.
- At a step boundary with a long context, say in one line that this is a good point to clear the session: the plan holds the state.

## 6. Gates

Commit every step marked "not committed (sandbox)" first, with the user's approval; until then the work is not landable. Rows the user kept uncommitted stay so: their gates run on the uncommitted work and are logged as such, and the work is reported as not landable until they are committed. Run python3 $S/floor_check.py: it reports removed tests, added skips and suppressions, the diff's size and its risk surfaces, reading each untracked file as added lines (a binary one is listed, not scanned); a quick change that outgrew its lane is raised to the full lane and reviewed as one; name each removed test or skip in the report. Exit 2 means it could not run: fix the cause and run it again, never read it as clean. When it prints "docs or comments only: yes", the full gates are the documented checks that read the changed files (a docs build, a link or format check, the tests that read them), not the build and the whole suite; name which ran and why. Then the full gates once on the last commit through gate-runner, given the folder, the commit, and each documented command wrapped as python3 $S/check_step.py --step final --gate --tail 0 -- <command>, so the log records it and gate-runner gets the whole output. The tests that pin the unchanged behavior must pass there too: run with check_step --gate any the gates do not run. Compare the final test count of the baseline's command with the step base line of the log (the base commit's, never a resume baseline) and name the tests behind a drop. Fix failures in the code. When the change has a runnable app (a command line tool, a server, a user interface), run it once in a fresh instance, never the user's running one, along each acceptance path, and record what you saw; when it cannot run here, mark that criterion as the user's check. A test the runner skips for a missing environment has not run: name it in the final reply with the setup script that would let it run, and keep Status in progress until it has. A SKIP or INCOMPLETE gate has not passed: list it with its reason and keep Status in progress; set in review only when every gate passed on the last commit.

## 7. Review and triage

- Delegate to reviewer (skip it when the user pinned no review), mode quick for the quick lane and full for the full lane or when the user pinned a thorough review, with the intent, the folder and the expected HEAD, the base, the plan path and its log path (return: findings ranked, the HEAD line, not verified, gates not run).
- For each finding, check it at its location and write a Review row with one verdict: real, keeping the reviewer's severity (blocker, major or minor; never lower it), false with a disproof the reviewer could read (a file and line, a test, a command's output; that it is intentional is not one), or undecided with what would settle it.
- Fix in one pass what this change caused when the fix is simple, each behavior-changing fix proven by a test seen failing first (--expect-fail). A fix that needs the user's choice is a stop (a choice of the user's the plan lacks); any other fix that is not simple is made and recorded as a ruling. Minor findings and open points this change caused are fixed too when the fix is simple; the rest go to the user as one question (fix them all, pick, or leave them listed). An issue the base commit also has goes to .private/deferred.<ext>. A finding that shows the plan wrong sends the work back to section 3 (at most three times); one that shows the intent wrong stops it.
- After fixes, run floor_check and the full gates again on the new last commit. A second reviewer pass, limited to the fixes (continue the same reviewer where the tool can), only when the risk is high, a fix added a public surface or the user pinned a thorough review; its findings are triaged as above.

## 8. Finish

Set Status built (every gate passed on the last commit) and Next to the user's landing. Before the final reply, stop the background agents, jobs and app instances this session started, and name any left running. Reply opening with one line: Done: yes or Done: no, what is left for the user and what is left for you. Then: the plan path; the lane and risk; the commits; the last commit's hash with each gate's result; how to check each acceptance criterion (the command or steps and the visible result to expect, marking each that needs a human look); the rulings still pending, one line each; the refuted assumptions; the findings not fixed, each with its verdict; the deferred lines added; and when work remains for a new session, the exact prompt to paste there, in a fenced block. Landing goes through isolated-work on the user's go. Never push.
