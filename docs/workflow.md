# Workflow guide

How the pieces work together once installed. The method is the same in every chat
and every project because claude.ai and every local agent read the same global
instructions.

## Two-way maieutic method

- You question the agent Socratically ("why?", "what are you assuming?"): it answers that question, changes nothing unless asked, and shows evidence, assumptions and what would prove it wrong.
- The agent guides you on choices that are yours (scope, public API, architecture, rules): the decide skill establishes what is known, isolates the missing information, asks one question at a time with a recommended option and the consequence of each option, and records the decision after your explicit confirmation. Up to four independent, low-stakes questions may share one message.
- When you ask to learn, the Learning section and the tutor skill give graded help and announce every check.
- Not maieutic, by design: routine engineering inside an approved plan, plain questions, clear requests, and "decide" (the agent chooses with its recommendations and lists the assumptions).

## Daily loop in a repository

| Situation | What to run |
|---|---|
| Small fix | Ask directly. Hooks block gate bypasses, flag em and en dashes, format C and C++ |
| Feature or design work | spec (raise the effort), then a fresh session, then implement on the spec file, then session-close |
| A choice that is yours | decide |
| Before commit or PR | review |
| Build and tests | gates, or gates narrow <module or test filter> |
| New repository or audit | project-setup |

Slash command form in Claude Code, Copilot and Cursor: /name. Codex: $name. Gemini CLI activates a skill when you ask for it in words.

The subagents keep the main conversation small: scout maps code and docs read-only, gate-runner runs builds and tests and returns only verdicts and first errors, reviewer reviews a finished change in a fresh context.

## Context hygiene

- One task per session; start a fresh session (Claude Code: /clear) between unrelated tasks.
- After a compaction or a resume, a hook reminds the agent that its memory of the code is a summary and prints the real branch, changes and last commits.
- Specs, progress logs and handoffs live in .private/ inside each repository (git-ignored); decisions live in the project's decision log.
- implement keeps .private/progress/<slug> current after every step: steps with commits and checks, and every decision marked by you or by the agent. Agent decisions stay "Review: pending" until you keep or change them; implement and session-close list the pending ones.
- Check where tokens go with /context and /usage in Claude Code.

## Per project

Everything global works in every repository. Each repository needs its own layer once:
an AGENTS.md with the project's facts (commands, rules, where files go), a decision
log, an agent workflows doc, and .private/ in .gitignore. Run project-setup in the
repository root to create or audit it. Add a project skill only for a recipe you
repeat that AGENTS.md does not already describe.

## Setup

1. claude.ai: paste home/.agents/AGENTS.md into Settings > General > Instructions for Claude, then upload the skill set (claude-ai/README.md).
2. Linux or macOS: install Claude Code (curl -fsSL https://claude.ai/install.sh | bash), sign in with your claude.ai account, install any other agents you use, then run python3 install.py --dry-run and python3 install.py from this repository.
3. Cursor only: paste ~/.agents/AGENTS.md into Settings > Rules > User Rules. Codex only: approve the hooks when it asks.
4. Check in Claude Code: /memory, /skills, /agents, /hooks, and that git commit --allow-empty -m test --no-verify is blocked.

After changing anything in this repository, run python3 install.py again, and update the claude.ai copy of AGENTS.md or the uploaded skills when those changed.
