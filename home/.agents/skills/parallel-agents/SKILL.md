---
name: parallel-agents
description: "Coordinates several coding agents writing at once in one git repository: decides whether the work splits, gives each agent its own worktree, build folder, scratch folder and files, writes the briefs, watches progress, and lands each branch on a commit that passed the gates. Use when the user asks to run agents, subagents or sessions in parallel on a repository, to split a feature or refactor across agents, or to merge the branches they produced."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Parallel agents

You are the coordinator: you split the work, brief the agents, merge their branches and own everything they share (the target branch, the main checkout, the user's decisions). The agents only write code on their own branches.

## 1. Decide whether to split

- Default to one writing agent. Run writers in parallel only for tasks that touch different files and do not need each other's results; reading (mapping, review) parallelizes safely. Parallel writers cost several times the tokens of one agent and rarely finish much sooner, because integration is serial.
- Start with up to 3 writers and never run more than 5: beyond that, results get worse, not faster.
- Settle the choices that belong to the user before launching (decide skill): an agent that meets an open choice guesses, and two agents guess differently.
- A change that applies one rule across many files splits by the mechanical-changes skill.
- Show the split before launching (the agents, the files each owns, the base, the target branch, the gates) and wait for the user's approval. The target is an integration branch unless the user asked to merge into main or master. With the implement skill, you do its steps 1 to 4 for the whole task and each brief carries its approved plan steps, so an agent starts at step 5 and needs no approval of its own.
- Keep your own progress log for the whole task (implement section 5): the split, the target, the merge order and how you resolved each conflict.

## 2. Isolate each agent

| Shared thing | How it is isolated |
|---|---|
| working tree | one git worktree per agent, outside the main checkout (a sibling folder), created from the base the work targets: git worktree add -b <branch> <path> <base> |
| build directory | one per worktree, used only with the toolchain that configured it (a build directory made inside a container is built only inside it) |
| scratch files | one subfolder per agent, named in its brief |
| source files | one owner per file. Two tasks that need the same file run one after the other: the second starts from the target after the first is merged |
| target branch and main checkout | only the coordinator touches them |

A new worktree holds no git-ignored files (.env, local instruction files, private notes) and no build: copy in what the agent needs, or tell it what is missing. Keep the machine awake during long runs: a session caught by sleep mid-response can come back unresponsive.

Tool notes:

- Claude Code: a subagent starts in your working directory and cannot be moved into a worktree made with git. Pass isolation worktree on the call instead: it branches from the remote's default branch, or from your current HEAD when the worktree.baseRef setting is "head" (it cannot name a branch). Those worktrees live under .claude/worktrees inside the checkout: keep it ignored by git and by tools that walk the files (linters, test discovery, validators). For any other base, start a separate claude session inside each worktree made with git. In an interactive session with agent teams enabled, a named subagent runs as a teammate in the main checkout unless the call itself passes isolation or is a fork; isolation in the subagent's definition does not prevent it.
- Codex: the default sandbox makes .git read-only, so an agent cannot commit. Before launching, give it a permissions profile (a beta feature) that extends :workspace and makes .git writable, for a linked worktree the main repository's .git as well; otherwise the agent stops after each step, uncommitted, and you commit it.
- Gemini CLI: subagents get no worktree of their own and stop after a default number of turns and minutes (max_turns, timeout_mins) too small for implementation; run a separate gemini session per worktree (gemini --worktree needs the experimental.worktrees setting, or start gemini inside a worktree made with git).
- Elsewhere (Copilot CLI, Cursor): start a separate session inside each worktree.

## 3. Write each brief

An agent knows this conversation only through its brief (it does load the project's instruction files). Each brief holds:

- the goal and why it matters, the user's binding decisions quoted, and what was ruled out;
- its worktree path, branch, base commit, scratch folder and progress log path (.private/progress/<slug>-<agent>.<ext>, so the logs of agents on one spec do not collide); the files it owns and the folders it must not touch; the other agents running and what they own;
- where to start (files and lines), as a starting point: it reports where it had to go beyond it;
- the build and test commands for its worktree, the commit style and the gates;
- the rules: follow the implement skill from step 5 with the plan steps in this brief, when available; commit each verified step; never merge, push, or touch the target branch or the main checkout; stop and report at a choice that belongs to the user; report anything it finds that affects another agent;
- what to return: its commits, the tests it saw failing first, the gate results with the commit they ran on, and what is left open.

## 4. Watch

- Judge progress from commits, logs and the tool's own state (in Claude Code, /tasks for subagents, and claude agents --json or the agent view for background sessions), not from silence. Message an agent that seems stuck before restarting it.
- An agent stopped by an error or a usage limit resumes from its commits: tell it what is done and what comes next.
- Stop each agent once its report has arrived: idle agents keep using tokens.
- Run timing measurements only while no other build runs: a parallel build slows them several times.

## 5. Land each branch

Land into the target of the approved split, one branch at a time, the one others depend on first, each through steps 1 to 6. git merge-tree --write-tree <target> <branch> shows conflicts without changing anything. Shell variables do not survive between commands: write the pinned hash into each command.

1. Pin the commit: run git rev-parse <branch> and use that hash from here on, so commits the agent adds later are not merged unseen.
2. Rebase the branch onto the target's tip in its worktree (git -C <path> rebase <target>, resolving conflicts yourself, or resume its agent to do it) and pin the rebased commit. Run the full gates on that commit (gate-runner): rebased commits have never been tested, and two branches that pass alone can fail together.
3. Merge it where the target is checked out, in the project's merge style (git merge --no-ff <hash>). If the target is checked out nowhere, check it out in a temporary worktree for the merge, so the hooks and signing run, and remove that worktree afterwards.
4. Confirm git diff --quiet <hash> <target>: the merge added nothing the gates did not see. If it differs, run the gates on the merge.
5. Clean up: first copy the agent's progress log and any git-ignored notes it hands over into the main checkout, because removing a worktree deletes its ignored files; then git worktree remove <path> (a branch checked out in a worktree cannot be deleted). Delete the branch with git branch -D <branch> only if git rev-parse <branch> still prints the pinned hash and git merge-base --is-ancestor <hash> <target> succeeds; if the branch moved, the agent added commits after the pin: report them. Do not rely on git branch -d: it compares with the branch's upstream or the current HEAD, not with the target.
6. Before anyone tests the result, restart whatever still runs an older build, and check that the build is newer than the merge.

## 6. Report

For each agent: its branch, the merged commit, the gate results on it, what is left open, and the decisions waiting for the user, including the agent decisions its progress log marks Review: pending. Then what is still running, and the worktrees and branches left to clean up.
