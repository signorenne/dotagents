# dotagents

One setup for every coding agent and for claude.ai: global working instructions,
skills, subagents and safety hooks, installed for Claude Code, Codex, Gemini CLI,
GitHub Copilot CLI and Cursor from a single source.

What it gives every session, in chat or in a repository:

- the same global instructions everywhere (priorities, sufficiency, evidence, output rules, no em dashes), including a two-way Socratic method: you question the agent, and the agent settles your decisions with you one question at a time;
- a repository workflow as skills: spec, implement, review, gates, session-close, decide, project-setup;
- three subagents that keep the main context small: scout (read-only mapping), gate-runner (builds and tests, returns only verdicts), reviewer (independent review);
- hooks that block git gate bypasses and force pushes, flag em and en dashes, run clang-format, and remind the agent after a compaction that its memory of the code may be stale;
- a claude.ai skill set (decide, tutor, debugging, verification, scoping, editing, research, decisions, handoffs, prompts), installed locally from this repository for every agent too.

## Quick start

```sh
git clone https://github.com/signorenne/dotagents.git ~/dotagents
cd ~/dotagents
python3 install.py --dry-run   # shows every change, touches nothing
python3 install.py             # installs for the agents found on this machine
```

The installer detects the agents present (~/.claude, ~/.codex, ~/.gemini, ~/.copilot,
~/.cursor or their commands on PATH), moves every file it replaces to
~/.agents-backup/<timestamp>/, and is safe to run again: a second run changes nothing.
It needs only python3 (3.9 or later).

Then:

1. claude.ai: paste home/.agents/AGENTS.md into Settings > General > Instructions for Claude, and upload the skill set as described in claude-ai/README.md.
2. In any repository, run project-setup once to give it its AGENTS.md, decision log and agent workflows.

The full guide, including the daily loop and the maieutic method, is docs/workflow.md.

## Update

```sh
cd ~/dotagents
git pull                       # or: git am <file>.patch
python3 install.py --dry-run
python3 install.py
python3 install.py --audit     # what in the agents' folders is not from here; changes nothing
```

Then, only for what the update touched: paste home/.agents/AGENTS.md into claude.ai
again, and upload the changed claude.ai skills (claude-ai/README.md, "Update a skill").
To change the setup itself, run Claude Code (or any agent) in this repository: its
AGENTS.md says where each change goes and which checks to run.

## What goes where

| Agent | Global instructions | Skills | Subagents | Hooks |
|---|---|---|---|---|
| Claude Code | ~/.claude/CLAUDE.md imports ~/.agents/AGENTS.md | every skill linked in ~/.claude/skills; synced claude.ai copies turned off | ~/.claude/agents | ~/.claude/settings.json, plus SessionStart after compact or resume |
| Codex | ~/.codex/AGENTS.md link | reads ~/.agents/skills | ~/.codex/agents/*.toml | ~/.codex/hooks.json (approve in Codex) |
| Gemini CLI | ~/.gemini/GEMINI.md link; context.fileName adds AGENTS.md | reads ~/.agents/skills | ~/.gemini/agents/*.md | ~/.gemini/settings.json |
| Copilot CLI | ~/.copilot/copilot-instructions.md link | reads ~/.agents/skills | ~/.copilot/agents/*.agent.md | ~/.copilot/hooks/agents-global.json |
| Cursor | paste AGENTS.md into User Rules | reads ~/.agents/skills | reads ~/.claude/agents | reads the Claude Code hooks |

Claude Code is tested end to end; the other agents' files follow their official documentation and are covered by the installer tests.

## Repository layout

```text
home/.agents/       the installed source: AGENTS.md, skills/, agents/, hooks/
claude-ai/          skills uploaded to claude.ai, and overrides for local skills uploaded too
adapters/claude/    Claude Code settings: permissions, hooks, no AI attribution
install.py          cross-agent installer
tools/              validate.py (format and text rules), build.py (zips into dist/)
tests/              unittest suites for hooks, installer and tools
docs/               workflow guide and decision log
```

## Development

```sh
python3 tools/validate.py
python3 -m unittest discover -s tests
python3 tools/build.py      # dist/claude-ai/<skill>.zip, dist/claude-ai-skills.zip, dist/project-kit.zip
```

Rules for changing the repository are in AGENTS.md; the reasons behind the setup are in docs/decisions.md.

## License

MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). The tutor skill is adapted from Anthropic's learn skill and keeps its Apache License 2.0; see claude-ai/skills/tutor/NOTICE.txt.
