---
name: project-setup
description: "Sets up or audits a repository for work with coding agents and gives it the project doc set, in the repository's doc format, filled with verified facts and with the direction drafted for the user's confirmation: AGENTS.md from what the repository actually does (with every validation command run once), the Claude, Gemini and Copilot bridges, vision, design, style guide and contributing docs (an AI disclaimer on request), and in the docs folder a docs map with a role matrix, a writing guide, a decision log and agent workflows; it also git-ignores local plans, designs and handoffs. Use when the user asks to set up, bootstrap, audit, improve or review a repository's agent instructions (AGENTS.md, CLAUDE.md, GEMINI.md) or its project docs (vision, design, style guide, contributing, docs map). Prefer it over the built-in init. Not for as-built docs of existing code (as-built-docs), a spec or design doc for one increment (spec), or the requirements and architecture of a new system (architecture-doc)."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne). See LICENSE.txt"
---

# Project setup

Templates live in the templates/ folder next to this file (in Claude Code: ${CLAUDE_SKILL_DIR}/templates; elsewhere ~/.agents/skills/project-setup/templates). Every <FILL: ...> marker must be replaced with verified facts or the line removed; none may remain in the result. A template names other docs by file name (VISION, the docs map): write each as a link with the path where that doc lives, and drop the mention of a doc the run does not create. A sentence a template states outside a marker is a default: it stays only where the repository shows nothing else.

## 1. Survey (delegate to scout)

Collect, citing files: languages, build system and its exact commands, test runner and how to run one test, linters and formatters, CI jobs, docs location and prose format (Org, Markdown), commit convention (from git log and contributing docs), existing agent files (AGENTS.md, CLAUDE.md, GEMINI.md, .github/copilot-instructions.md, .cursor/rules, .claude/), whether .private/ is git-ignored, every existing doc with the topics it owns (a style section in a README counts), and whether the repository holds code or only docs or configuration. Tell scout to return these items, each cited, instead of its standard brief.

## 2. Decide the open points with the user

Use the decide skill only for what the repository does not answer, typically where docs go and in which format when it is mixed; without a docs folder, use docs/ in the format of the root README, or Markdown without one. Then list, and wait for the user's go:

- the files you will create or change, each with its source template;
- the docs of the set you skip and why: STYLE_GUIDE without code, AI_DISCLAIMER unless the request asks for it;
- each topic an existing doc already owns, which the new doc links to; moving that content into the new doc happens only on the user's yes to this line;
- the style defaults the user may drop, where the repository shows no convention of its own: no em or en dashes, the words to avoid, the commit subject form, the branch model.

## 3. AGENTS.md

- If AGENTS.md exists: audit it against templates/AGENTS.md.template. Propose only missing sections and wrong facts as a minimal diff; never rewrite it wholesale. Keep the project's voice.
- If it does not exist: draft it from the template, filling each section from the survey. Keep it under about 200 lines; a line belongs there only if removing it would cause an agent to make a mistake.
- Validation commands: run each command once (delegate to gate-runner when output is long). Keep only commands that worked; mark any you could not run as "not verified" and tell the user.
- If CLAUDE.md, GEMINI.md or .github/copilot-instructions.md duplicates rules or does not point to AGENTS.md, propose replacing it with its bridge from templates/bridges/, keeping its notes for that tool alone below the pointer: Claude Code reads AGENTS.md only when there is no CLAUDE.md, so a CLAUDE.md that merely mentions AGENTS.md without importing it leaves it without the rules.
- Create the three bridges when missing, without asking: CLAUDE.md from templates/bridges/CLAUDE.md.template, GEMINI.md from templates/bridges/GEMINI.md.template and .github/copilot-instructions.md from templates/bridges/copilot-instructions.md.template. Every tool then reaches AGENTS.md without per-machine settings (Copilot CLI and Cursor, which also read CLAUDE.md, load the rules twice, and Gemini CLI may too where its context.fileName also names AGENTS.md; that cost is accepted). Codex needs none: AGENTS.md is its own file. With a CLAUDE.md, Claude Code no longer reads nested AGENTS.md files by itself: check what it loaded (/memory) and give each folder whose AGENTS.md it does not load a CLAUDE.md that imports it.

## 4. Project docs

Create each doc of the set that is missing, in the repository's prose format: from templates/root-md/ or templates/root-org/ at the root VISION, DESIGN, STYLE_GUIDE (only when the repository has code), CONTRIBUTING and AI_DISCLAIMER (only when the request asks for it); from templates/docs-md/ or templates/docs-org/ in the docs folder README (the docs map), writing, decisions and agent-workflows. A glossary or a file-system doc is not part of the set: the guides of as-built-docs carry the vocabulary and the folder table.

- One owner per concept: where an existing doc already owns a topic, the new doc links to it instead of repeating it.
- VISION's mission, principles and non-goals, and DESIGN's north star and documentation design, are the maintainer's direction: draft them from the README, the existing docs and the rules the code and the build enforce, mark each inferred line as inferred, and show the draft to the user before writing it; the marks come out once the user confirms.
- Every other rule written into DESIGN and STYLE_GUIDE, apart from the template defaults, is one the code and its tooling already enforce, with the file that shows it.
- A convention the repository already shows (its branch model and commit subjects in git log, its docs' punctuation) wins over a template default.
- Fill the component change workflow of agent-workflows from the repository's real recipe, or delete that section if the project has none yet.
- The docs map registers every doc of the set and every doc the repository already had, with its real path, and gives each a row in the role matrix when a role loads it. AGENTS.md's First load links the docs map and each doc of the set.
- If a doc of the set exists, audit it as step 3 audits AGENTS.md: propose only missing sections and wrong facts.

## 5. Local notes and settings

Append templates/gitignore-snippet.txt to .gitignore when those lines are missing. If the user uses Claude Code here and wants fewer permission prompts, offer templates/claude/settings.json filled with the project's build and test command prefixes, merged into an existing .claude/settings.json.

## 6. Project skills (only on request)

Run this step only when the user asks for a project skill. For a recipe the user repeats in this repository, create .agents/skills/<name>/SKILL.md from templates/project-skill/SKILL.md.template. Claude Code reads project skills from .claude/skills, so also create the symlink .claude/skills/<name> -> ../../.agents/skills/<name>.

## 7. Report

First run grep -rn "<FILL" on the files you created or changed and fix every match. Then list files created or changed, the docs of the set skipped and why, commands verified and their results, commands not verified, and decisions recorded; name in one line the recipes that could become project skills. Commit only if the user asks, in the project's convention, one logical change per commit.
