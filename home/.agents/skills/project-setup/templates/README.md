# Project kit

What every repository gets for agent work, and how to tailor it. The project-setup
skill uses these same templates: in a repository, ask your agent for project-setup
and it performs the steps below, running the real build and test commands before
it writes them down.

## Files

| Kit file | Goes to | Required |
|---|---|---|
| AGENTS.md.template | AGENTS.md at the repository root | yes |
| root-md/ or root-org/ | the repository root (VISION, DESIGN, STYLE_GUIDE, CONTRIBUTING, AI_DISCLAIMER) | yes, in the project's prose format; STYLE_GUIDE only with code, AI_DISCLAIMER only on request |
| docs-md/ or docs-org/ | the project's docs folder (README as the docs map, writing, decisions, agent-workflows) | yes, in the project's prose format |
| gitignore-snippet.txt | appended to .gitignore | yes |
| bridges/CLAUDE.md.template | CLAUDE.md at the repository root | yes |
| bridges/GEMINI.md.template | GEMINI.md at the repository root | yes |
| bridges/copilot-instructions.md.template | .github/copilot-instructions.md | yes |
| claude/settings.json | .claude/settings.json, for fewer permission prompts | no |
| project-skill/SKILL.md.template | .agents/skills/<name>/SKILL.md, plus the symlink .claude/skills/<name> | no |

## Tailoring checklist

1. Replace every <FILL: ...> marker with verified facts, or delete the line. Check: grep -rn "<FILL" finds nothing.
2. Validation commands: run each command once before writing it down.
3. Hard rules: keep only rules whose absence would make an agent err; keep AGENTS.md under about 200 lines.
4. Link every doc of the set from AGENTS.md's First load, and register each, with every doc the project already had, in the docs map. A template names other docs by file name: write each as a link with its real path, and drop the mention of a doc the repository will not have after the run.
5. Rules for one subtree only: a nested AGENTS.md in that folder (read by Codex, Copilot and Cursor), with a CLAUDE.md bridge next to it for Claude Code, which reads AGENTS.md files by itself only in a project without a CLAUDE.md.

## Why the bridges

AGENTS.md is the single source. Codex, Copilot and Cursor read it natively;
Claude Code reads it only when no CLAUDE.md exists, and Gemini CLI only when its
context.fileName setting includes AGENTS.md. CLAUDE.md and GEMINI.md only import
AGENTS.md, and .github/copilot-instructions.md only points to it, so every tool
reaches the same rules on any machine, without per-machine settings, and each
bridge has room for notes one tool alone needs. The cost: Copilot CLI and Cursor,
which also read CLAUDE.md, load the rules twice, and Gemini CLI may too where its
context.fileName also names AGENTS.md (the dotagents installer sets it so).
