---
name: review
description: "Runs an independent review of the current branch against the project's rules, review checklist and accepted decisions by delegating to the reviewer subagent, and returns findings ranked by severity. Use when the user asks to review a change, a branch or a diff before committing, merging or opening a PR."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Review

1. Determine the inputs:
   - base ref: the one the user gave, else the merge base with main (fall back to origin/main, then master);
   - intent: the one the user gave, else infer it from the commit subjects since the base and state it in one line.
2. Delegate to reviewer with the base ref and the intent. Ask it to include uncommitted and untracked changes.
3. Relay its findings as returned (blocker, major, minor with path:line), then its "Not verified" and "Gates not run" lists. Do not soften, merge or drop findings, and do not start fixing unless the user asks.

If no reviewer subagent is available, perform the review yourself following ~/.agents/agents/reviewer.md, after re-reading the changed files from disk.
