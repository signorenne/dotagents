# claude.ai skill set

Skills uploaded to claude.ai so they work in chat and Cowork. install.py also installs
them locally from this repository for every agent (~/.agents/skills, linked into
~/.claude/skills). claude.ai syncs its own copies to Claude Code as
anthropic-skills:<name>, and Claude Code would list each skill twice, so install.py
turns those synced copies off with skillOverrides in ~/.claude/settings.json. The
repository is the source: edit skills here, never on claude.ai.

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

## Update a skill

1. Edit claude-ai/skills/<name>/ (for decide: home/.agents/skills/decide/, and its claude.ai description in overrides.json).
2. Run python3 tools/validate.py, python3 -m unittest discover -s tests and python3 tools/build.py, then commit.
3. Run python3 install.py: every local agent uses the new version.
4. claude.ai: in Customize > Skills delete the old version of the skill, then upload dist/claude-ai/<name>.zip.
