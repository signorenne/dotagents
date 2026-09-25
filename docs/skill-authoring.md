# Skill authoring

Owns how skills in this repository are written and checked. The mechanical rules
(frontmatter fields, license, characters) are in AGENTS.md under Hard rules and are
enforced by tools/validate.py; the decision behind this guide is D-0013 in
docs/decisions.md.

## Principles

1. Concise and complete. A skill holds every step and rule a model would otherwise
   get wrong, each stated once, and nothing else. Once a skill loads, every token
   competes with the conversation for the model's attention [1][2], and adherence
   drops as the number of instructions grows [3]. Concise does not mean vague:
   guidance with no concrete signal is a failure too [2].
2. Assume a capable model. Do not explain what it already knows (what a PDF is, how
   git works, why tests matter). Give a reason only where the rule is not obvious,
   so the model can apply it to cases the text does not name.
3. The description triggers the skill. Third person, what it does and when to use
   it, in the words a user would type. At most 1024 characters, 200 for the
   claude.ai set. Check it against the descriptions of the other skills so two do
   not compete for the same request.
4. Specificity follows fragility. Exact steps where a mistake is costly or the
   order matters (commits, deletions, verification); heuristics where context
   decides (design, writing) [1].
5. One default, not a menu. Name the recommended path and, at most, the one case
   that needs another [1].
6. A loop for quality-critical work: produce, check with something that can fail,
   fix, check again [1].
7. Progressive disclosure. SKILL.md stays under 500 lines [1]. Bulky detail needed
   only in some runs goes in a file next to SKILL.md, linked directly from it (one
   level deep), with what it contains and when to read it. Default to a single
   SKILL.md: add a reference file or a script only when a real run showed the need.
8. Consistent terms (one word per concept), no time-sensitive statements, and an
   example only where it shows the expected output better than a rule does [1].
9. Portable. Local skills run in Claude Code, Codex, Gemini CLI, Copilot CLI and
   Cursor; the claude.ai set also runs in chat, without a repository, shell or
   subagents. A step that needs a feature one of them lacks says what to do there.

## Checklist before committing a skill

- Description: what and when, third person, user's words, no overlap with another
  skill.
- Every step and rule earns its place: would a capable model get this wrong
  without it?
- Nothing stated twice, nothing the global instructions (home/.agents/AGENTS.md)
  already say, nothing contradicting them or an Accepted decision.
- Every skill, subagent, file, command and flag it names exists and works.
- python3 tools/validate.py, python3 -m unittest discover -s tests and
  python3 tools/build.py pass.
- Tested in a real session (below), noted in the commit or PR.

## Testing a skill

Test with use, not by rereading [1]:

1. Run the skill in a fresh session on a real, small task (the session that wrote
   the skill knows too much to show its gaps).
2. Watch where it goes wrong: a skipped step, a wrong default, a rule it ignored,
   a question it should not have asked.
3. Fix only that, with the smallest change, and run it again.
4. When a skill runs on several models (subagents use Sonnet, sessions often
   Opus), test on the smallest one it will meet: what Opus infers, a smaller
   model may need spelled out [1].

## Sources

1. Anthropic, Skill authoring best practices (vendor documentation):
   https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
2. Anthropic, Effective context engineering for AI agents (vendor engineering
   article): https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
3. Jaroslawicz et al., How Many Instructions Can LLMs Follow at Once? (IFScale,
   NeurIPS 2025 benchmark of simple keyword instructions; read it as a direction,
   not a measure for skills): https://arxiv.org/abs/2507.11538
