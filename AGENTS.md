# dotagents agent guide

Guide for AI agents and contributors changing this repository. dotagents is the
source of a personal, cross-agent setup: global rules, skills, subagents and
hooks for Claude Code, Codex, Gemini CLI, GitHub Copilot and Cursor, an installer
that wires them into each tool, and a skill set for claude.ai. The global rules for
how agents work live in home/.agents/AGENTS.md; this file covers only how to change
the repository itself.

## Layout

```text
home/.agents/AGENTS.md     global rules, installed as ~/.agents/AGENTS.md
home/.agents/skills/       local skills (decide, spec, implement, review, gates, session-close, project-setup, as-built-docs, architecture-doc, plantuml-diagrams, parallel-agents, isolated-work, mechanical-changes, precise-ui-changes, qt-quick, clean-architecture, event-driven-ui, code-audit)
home/.agents/agents/       subagents in Claude Code format, the source for every tool's copy
home/.agents/hooks/        hook scripts shared by every agent
claude-ai/skills/          skills uploaded to claude.ai (and installed locally for every agent)
claude-ai/overrides.json   local skills also uploaded to claude.ai, with their short description
adapters/claude/           Claude Code settings merged by the installer
install.py                 installer: copies the source and generates each tool's files
tools/                     validate.py and build.py
tests/                     unittest suites for hooks, installer, tools and skill scripts
docs/                      Org docs: docs map, architecture, pipeline, workflow guide, skill authoring guide and glossary
*.org at the root          README, VISION, DESIGN (with the rules that bind), CONTRIBUTING, AI_DISCLAIMER; the bridges CLAUDE.md, GEMINI.md and .github/copilot-instructions.md point here
```

## Where changes go

- A rule for every agent and every chat: home/.agents/AGENTS.md (keep it under 200 lines; the same text is pasted into claude.ai).
- A repo workflow (spec, implement, review...): a skill in home/.agents/skills/<name>/.
- A general skill also wanted in claude.ai chat: claude-ai/skills/<name>/. A local skill wanted there too: an entry in claude-ai/overrides.json, never a copy.
- A script a skill runs: home/.agents/skills/<name>/scripts/. It uses only the standard library plus at most one common package, and has tests in tests/test_skill_scripts.py that run in CI without that package.
- A subagent: home/.agents/agents/<name>.md; per-tool formats come from install.py, never by hand.
- A hook: a script in home/.agents/hooks/ with tests in tests/test_hooks.py, registered for each tool in install.py and, for Claude Code, in adapters/claude/settings.json.
- A new tool or a format change: install.py, with a test in tests/test_install.py.
- A new check: tools/validate.py, with a test in tests/test_tools.py.

## Hard rules

- Skills use only the frontmatter fields name, description and license (the Agent Skills specification also allows compatibility, metadata and allowed-tools; fields only Claude Code knows make the claude.ai upload fail); the name equals the folder name; descriptions are third person, say what and when, at most 1024 characters (200 for claude.ai).
- Every skill folder has a LICENSE.txt. New work is MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). Adapted third-party work keeps its license and records the changes (see claude-ai/skills/tutor/NOTICE.txt).
- No em dash or en dash characters anywhere, and no inline backticks in skill prose.
- Instructions are written for models: a positive instruction, a reason only where the rule is not obvious, an example where it shows the expected output, no capitalized emphasis.
- Change a skill's behavior only on purpose. Skills are concise and complete (every step and rule a model would otherwise get wrong, stated once) and follow docs/skill-authoring.org.
- Hooks never block on unreadable input and never print anything but JSON on Gemini CLI's stdout.
- Commit subjects: type(scope): description, lower case, imperative, one line, no body, no AI attribution trailers.

## Validation commands

```sh
python3 tools/validate.py
python3 -m unittest discover -s tests
python3 tools/build.py
```

Run all three before every commit. CI runs the same commands.

## Review checklist

- Does the change sit in its owning place (Where changes go), without a second copy?
- Do validate, tests and build pass?
- Does a changed instruction still agree with home/.agents/AGENTS.md and the rules in DESIGN.org?
- Does a new or changed skill pass the checklist in docs/skill-authoring.org?
- If the maintainer asked for a real agent session test of a behavior change, was it run, and do the progress log or the PR say whether it was?
