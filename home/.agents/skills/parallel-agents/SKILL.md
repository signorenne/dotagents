---
name: parallel-agents
description: "Coordinates several coding agents writing at once in one git repository: decides whether the work splits, gives each agent its own worktree, build folder, scratch folder and files, writes the briefs, watches progress, and lands each branch on a commit that passed the gates. Use when the user asks to run agents, subagents or sessions in parallel on a repository, to split a feature or refactor across agents, or to merge the branches they produced."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne). See LICENSE.txt"
---

# Parallel agents

You are the coordinator: you split the work, brief the agents, merge their branches and own everything they share (the target branch, the main checkout, the user's decisions). The agents only write code on their own branches.

## 1. Decide whether to split

- Default to one writing agent. Run writers in parallel only for tasks that touch different files and do not need each other's results; reading (mapping, review) parallelizes safely. Parallel writers cost several times the tokens of one agent and rarely finish much sooner, because integration is serial.
- Start with up to 3 writers and never run more than 5: beyond that, results get worse, not faster.
- Settle the choices that belong to the user before launching (decide skill): an agent that meets an open choice guesses, and two agents guess differently.
- A change that applies one rule across many files splits by the mechanical-changes skill.
- Show the split before launching (the agents, the files each owns, the base, the target branch, the gates) and wait for the user's approval. The target is an integration branch unless the user asked to merge into main or master. With the build skill, you do its sections 1 to 4 for the whole task (one plan, approved once) and give each agent its own plan file holding its approved steps, so it starts at build section 5 and needs no approval of its own.
- Keep the whole task's plan file yourself: the split, the target, the merge order, how you resolved each conflict, and after each rebase which landed commit each agent commit became (the agents' plans name the hashes from before the rebase).

## 2. Isolate each agent

| Shared thing | How it is isolated |
|---|---|
| working tree | one git worktree and branch per agent, created and run as the isolated-work skill says (sections 1 and 2) |
| build directory | one per worktree, used only with the toolchain that configured it (a build directory made inside a container is built only inside it) |
| scratch files | one subfolder per agent, named in its brief |
| source files | one owner per file. Two tasks that need the same file run one after the other: the second starts from the target after the first is merged |
| target branch and main checkout | only the coordinator touches them, except each agent's own plan file and log in the main checkout's .private/plans/ |

Keep the machine awake during long runs: a session caught by sleep mid-response can come back unresponsive.

## 3. Write each brief

An agent knows this conversation only through its brief (it does load the project's instruction files). Each brief holds:

- the goal and why it matters, the acceptance criteria this agent owns, the user's binding decisions quoted, and what was ruled out;
- its worktree path, branch, base commit, scratch folder and plan file path (the absolute path of .private/plans/<slug>-<agent>.<ext> in the main checkout, so the agents of one task do not collide; its branch is <type>/<slug>-<agent>, the plan's slug, so the scripts and hooks find it); the files it owns and the folders it must not touch; the other agents running and what they own;
- where to start (files and lines), as a starting point: it reports where it had to go beyond it;
- the build and test commands for its worktree, the commit style and the gates;
- the rules: follow the build skill's sections 5 and 6 with the steps of its plan file, when available (no review of its own: the coordinator reviews the merged result), with the path of the coordinator's plan log, whose base line is the baseline section 6 compares with; commit each verified step; never merge, push, or touch the target branch or the main checkout, except its plan file and log in the main checkout's .private/plans/; stop and report at a choice that belongs to the user; report anything it finds that affects another agent;
- the model and effort it runs on: writers on the session's model and effort, since they make the code's choices;
- what to return, in at most 30 lines, opening with a status word (done, partial, blocked or needs-confirm, with its reason): its commits, the tests it saw failing first, the gate results with the commit they ran on, and what is left open.

## 4. Watch

- Judge progress from commits, logs and the tool's own state (in Claude Code, /tasks for subagents, and claude agents --json or the agent view for background sessions), not from silence. Message an agent that seems stuck before restarting it.
- An agent stopped by an error or a usage limit resumes from its commits: tell it what is done and what comes next.
- Stop each agent once its report has arrived: idle agents keep using tokens.
- Run timing measurements only while no other build runs: a parallel build slows them several times.

## 5. Land each branch

Land into the target of the approved split, one branch at a time, the one others depend on first. git merge-tree --write-tree <target> <branch> shows conflicts without changing anything.

1. Copy any git-ignored notes the agent left in its worktree into the main checkout's .private/ under their own names, because removing a worktree deletes its ignored files; its plan file is already there.
2. Land the branch as the isolated-work skill says (section 3: pin, rebase onto the target's tip, gate the pinned commit, fast-forward, remove the worktree and the branch), and note in your log which agent commit became which landed commit.
3. The branches still open rebase onto the new tip before their own landing: two branches that pass alone can fail together.

## 6. Report

With the build skill, once the last branch has landed, run its review and finish (sections 7 and 8) on the integrated result: everything the target gained since the base commit of the split. Then, for each agent: its branch, the merged commit, the gate results on it, what is left open, and the decisions waiting for the user, including the rulings its plan file marks pending. Then what is still running, and the worktrees and branches left to clean up.
