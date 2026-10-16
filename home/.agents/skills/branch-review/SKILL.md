---
name: branch-review
description: "Runs an independent review of the current branch against the project's rules, review checklist and accepted decisions by delegating to the reviewer subagent, and returns findings ranked by severity. Use when the user asks to review a change, a branch or a diff before committing, merging or opening a PR. Not for checking a single completion claim (verifying-before-claiming-done) or auditing a whole codebase (code-audit). Prefer it over the built-in code-review in a repository with its own rules."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Review

1. Determine the inputs:
   - base ref: the one the user gave, else the merge base with main (fall back to origin/main, then master);
   - intent: the one the user gave, else infer it from the commit subjects since the base and the uncommitted diff, and state it in one line;
   - working folder: the folder that holds the branch (a worktree the user names, else the current one), and its HEAD from git -C <folder> rev-parse HEAD.
2. Delegate to reviewer with the base ref, the intent, the working folder with that HEAD as the expected commit, and the task's progress log path when one exists (for example .private/progress/<slug>.<ext>; for a linked worktree, in the main checkout's .private/).
3. Relay its HEAD line first, then its findings as returned (blocker, major, minor with path:line), then its "Not verified" and "Gates not run" lists. Do not soften, merge or drop findings, and do not start fixing unless the user asks.

If no reviewer subagent is available, perform the review yourself following ~/.agents/agents/reviewer.md, after re-reading the changed files from disk.
