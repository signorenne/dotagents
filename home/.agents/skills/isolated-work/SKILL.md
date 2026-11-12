---
name: isolated-work
description: "Runs a complex or risky change in its own git worktree and branch so the main checkout stays untouched: creates the worktree from the right base outside the checkout, works there (through the implement skill), gates the exact commit, keeps the branch for the user's review, then lands it on the user's go by rebase and fast-forward for linear history, and removes the worktree and the branch. Use when a plan proposes isolation (a change across modules, a public API change, a data or many-file migration), when the user asks to work in a worktree or in isolation, or when another skill runs a change apart; parallel-agents uses it for each writer."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Isolated work

Goal: a change lives in its own folder and branch until the user has reviewed it. The main checkout and the target branch move only when the change lands, and nothing is left behind afterwards.

## 1. Create

- Base: the commit the work starts from, the tip of the branch it will land on (an integration or feature branch, or main when the user works there).
- Folder: outside the main checkout, a sibling folder, so tools that walk the checkout never see it: git worktree add -b <type>/<slug> ../<repository>-<slug> <base>.
- Record the worktree path, the branch and the base commit in the task's progress log.
- A worktree has no git-ignored files and no build. Build in the worktree's own build folder with the toolchain that configured the main one (a build folder made inside a container is built only inside it). Copy in only the ignored files the work needs (.env, local configuration) and never commit them.
- Notes stay in the main checkout's .private/: write the progress log and other notes there by absolute path, because a worktree has no .private/ and removing the worktree deletes its ignored files.

## 2. Work inside it

Run the change through the implement skill, inside the worktree: every command in that folder (cd <path> && ... when the shell does not keep the folder, or git -C <path>). Leave the main checkout alone, except its .private/ notes.

Running an agent there:

- Claude Code: a subagent starts in the session's folder and cannot be moved into a worktree made with git; give it the absolute worktree path and tell it to work only there, or start a separate claude session inside the worktree. Claude Code's own isolation (claude --worktree, or isolation worktree on a subagent) branches from the remote's default branch, or from the current HEAD when the worktree.baseRef setting is "head", and puts its worktrees under .claude/worktrees inside the checkout: use it only when that base is the right one, and keep that folder git-ignored.
- Codex: the default sandbox makes .git read-only, so commits, rebases and worktree commands need the user's approval, or a permissions profile (a beta feature) that extends :workspace and makes .git writable, for a linked worktree the main repository's .git as well.
- Gemini CLI: subagents have no worktree of their own; run a separate gemini session inside the worktree (gemini --worktree needs the experimental.worktrees setting).
- Elsewhere (Copilot CLI, Cursor): a separate session inside the worktree.

When the work is done (gates and review passed on its last commit), report the branch for review and keep the worktree until it lands or the user drops it.

## 3. Land on the user's go

Write every hash into the commands literally: shell variables do not survive between commands.

1. Pin: git -C <path> rev-parse HEAD.
2. Rebase onto the target's current tip in the worktree (git -C <path> rebase <target>), resolve conflicts there, and pin the rebased commit. Run the full gates on that exact commit through gate-runner, given the worktree path and the pinned hash: a rebased commit has never been tested.
3. Fast-forward the target to the pinned hash: where the target is checked out and clean, git -C <that checkout> merge --ff-only <hash>; where it is checked out nowhere, git update-ref refs/heads/<target> <hash> <old target hash> after git merge-base --is-ancestor <target> <hash> succeeds. Use a merge commit (git merge --no-ff) only when the project's documented convention asks for one.
4. Confirm git rev-parse <target> prints the pinned hash.
5. Remove: git worktree remove <path>. It refuses when the worktree has uncommitted changes: report them and never pass --force without the user. Then delete the branch with git branch -D <branch> only if git rev-parse <branch> still prints the pinned hash and git merge-base --is-ancestor <hash> <target> succeeds; if the branch moved, report the extra commits. Finish with git worktree prune.
6. Before anyone tests the result, restart whatever still runs an older build.

Pushing stays with the user.

## 4. When it goes wrong

- The user drops the change: remove the worktree and delete the branch only after the user confirms, and note it in the progress log.
- A worktree folder deleted by hand leaves a stale entry: git worktree prune.
- An interrupted task resumes from the progress log, which names the worktree, the branch and the base.
