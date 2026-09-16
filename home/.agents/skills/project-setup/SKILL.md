---
name: project-setup
description: "Sets up or audits a repository for work with coding agents: drafts or checks AGENTS.md from what the repository actually does (with every validation command run once), adds a decision log and agent workflows in the repository's doc format, git-ignores local specs and handoffs, and proposes project skills. Use when the user asks to set up, bootstrap, onboard or audit agent instructions for a project."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Project setup

Templates live in the templates/ folder next to this file (in Claude Code: ${CLAUDE_SKILL_DIR}/templates). Every <FILL: ...> marker must be replaced with verified facts or the line removed; none may remain in the result.

## 1. Survey (delegate to scout)

Collect, citing files: languages, build system and its exact commands, test runner and how to run one test, linters and formatters, CI jobs, docs location and prose format (Org, Markdown), commit convention (from git log and contributing docs), existing agent files (AGENTS.md, CLAUDE.md, GEMINI.md, .github/copilot-instructions.md, .cursor/rules, .claude/), and whether .private/ is git-ignored.

## 2. Decide the open points with the user

Use the decide skill only for what the repository does not answer, typically: where docs go and in which format when it is mixed, whether to add the GEMINI.md bridge (needed when contributors use Gemini CLI without context.fileName including AGENTS.md), and whether project skills are wanted now.

## 3. AGENTS.md

- If AGENTS.md exists: audit it against templates/AGENTS.md.template. Propose only missing sections and wrong facts as a minimal diff; never rewrite it wholesale. Keep the project's voice.
- If it does not exist: draft it from the template, filling each section from the survey. Keep it under about 200 lines; a line belongs there only if removing it would cause an agent to make a mistake.
- Validation commands: run each command once (delegate to gate-runner when output is long). Keep only commands that worked; mark any you could not run as "not verified" and tell the user.
- If CLAUDE.md, GEMINI.md or copilot instructions duplicate rules, propose turning them into pointers to AGENTS.md.

## 4. Decision log and workflows

Copy templates/docs-md/ or templates/docs-org/ (matching the repository's prose format) into its docs folder as decisions and agent-workflows. Fill the component change workflow from the repository's real recipe, or delete that section if the project has none yet. Register both files in the docs index when the project has one.

## 5. Local notes and settings

Append templates/gitignore-snippet.txt to .gitignore when those lines are missing. If the user uses Claude Code here and wants fewer permission prompts, offer templates/claude/settings.json filled with the project's build and test command prefixes.

## 6. Project skills (optional)

For a recipe the user repeats in this repository, create .agents/skills/<name>/SKILL.md from templates/project-skill/SKILL.md.template. Claude Code reads project skills from .claude/skills, so also create the symlink .claude/skills/<name> -> ../../.agents/skills/<name>.

## 7. Report

List files created or changed, commands verified and their results, commands not verified, and decisions recorded. Commit only if the user asks, in the project's convention, one logical change per commit.
