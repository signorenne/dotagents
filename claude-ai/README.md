# claude.ai skill set

Skills uploaded to claude.ai so they work in chat and Cowork, and sync to Claude Code
on every machine where you sign in with your claude.ai account (into
~/.claude/skills/synced/). install.py also copies them into ~/.agents/skills, so
Codex, Gemini CLI, Copilot and Cursor get them too.

| Skill | Use |
|---|---|
| decide | Settle a choice that belongs to you, one Socratic question at a time (built from home/.agents/skills/decide with a shorter description) |
| tutor | Learning: diagnosis, graded help, one step per turn (adapted from Anthropic's learn skill, Apache 2.0, see its NOTICE.txt) |
| scoping-before-building | Ask only the question that changes the result before building |
| systematic-debugging | Diagnose from evidence before any fix |
| verifying-before-claiming-done | Report what was verified and what was not |
| minimal-editing | Smallest complete change, show only the change |
| efficient-research | When and how much to search, primary sources first |
| decision-analysis | Compare options and commit to a recommendation |
| context-handoff | Self-contained brief to continue elsewhere |
| prompt-optimizer | Specific, checkable prompts and agent instructions |

## Upload

1. Run python3 tools/build.py: every skill becomes dist/claude-ai/<name>.zip.
2. claude.ai: turn on Settings > Capabilities > "Code execution and file creation".
3. Turn off what would clash by name: Anthropic's built-in learn skill (tutor replaces
   it; the name learn stays reserved even when turned off), and any installed plugin
   that provides a skill with one of the names above (remove the plugin if claude.ai
   still reports the name as in use).
4. Upload each zip: Customize > Skills > "+" > Create skill > Upload a skill.

claude.ai accepts skill descriptions of at most 200 characters; tools/validate.py
enforces that limit for this folder and for claude-ai/overrides.json.
