# Project kit

What every repository gets for agent work, and how to tailor it. The project-setup
skill uses these same templates: in a repository, ask your agent for project-setup
and it performs the steps below, running the real build and test commands before
it writes them down.

## Files

| Kit file | Goes to | Required |
|---|---|---|
| AGENTS.md.template | AGENTS.md at the repository root | yes |
| docs-md/ or docs-org/ | the project's docs folder (decisions, agent-workflows) | yes, in the project's prose format |
| gitignore-snippet.txt | appended to .gitignore | yes |
| bridges/GEMINI.md.template | GEMINI.md, only if contributors use Gemini CLI without the global setup | no |
| bridges/CLAUDE.md.template | CLAUDE.md, only for notes that apply to Claude Code alone | no |
| claude/settings.json | .claude/settings.json, for fewer permission prompts | no |
| project-skill/SKILL.md.template | .agents/skills/<name>/SKILL.md, plus the symlink .claude/skills/<name> | no |

## Tailoring checklist

1. Replace every <FILL: ...> marker with verified facts, or delete the line. Check: grep -rn "<FILL" finds nothing.
2. Validation commands: run each command once before writing it down.
3. Hard rules: keep only rules whose absence would make an agent err; keep AGENTS.md under about 200 lines.
4. Link decisions and agent-workflows from AGENTS.md and from the docs index, if the project has one.
5. Rules for one subtree only: a nested AGENTS.md in that folder (read by Codex, Copilot, Cursor and Claude Code).

## Why AGENTS.md alone

Claude Code (when no CLAUDE.md exists), Codex, Copilot and Cursor read AGENTS.md
natively; Gemini CLI reads it through the global setup (context.fileName). Bridges
help only people without that setup, and every extra bridge makes Copilot CLI and
Cursor, which also read CLAUDE.md, load the same rules twice.
