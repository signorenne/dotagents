# Decision log

Owns the record of decisions behind this setup: what was decided, why, who proposed
it, who accepted it. The maintainer decides; agents add entries as Proposed and write
Accepted only for decisions the maintainer explicitly accepted. Changed decisions get
a new entry, and the old one becomes "Superseded by D-NNNN".

## D-0001: One source of truth in ~/.agents, generated copies per tool

- Status: Proposed
- Proposed by: agent
- Date: 2026-10-07
- Rule in: AGENTS.md (this repository)
- Decision: Instructions, skills, subagents and hooks have one source (home/.agents, installed as ~/.agents). install.py links or generates each tool's files from it; nothing is edited in a tool's own folder.
- Why: Five agents read different file names and formats; hand-kept copies drift.
- Rejected: Per-tool copies maintained by hand; Claude Code only.
- Revisit if: the tools converge on one standard location for instructions, skills and subagents.

## D-0002: Learning stays in the global instructions

- Status: Accepted
- Proposed by: maintainer
- Decided by: maintainer
- Date: 2026-10-07
- Rule in: home/.agents/AGENTS.md
- Decision: The Learning section stays in the always-loaded global instructions, at a cost of about 600 tokens per session.
- Why: Nothing of the maintainer's rules may be missing in any context; the tutor skill adds depth on top.
- Rejected: Loading Learning only on demand as a skill.
- Revisit if: the global instructions approach the 200-line limit.

## D-0003: Grouping independent low-stakes questions is allowed

- Status: Accepted
- Proposed by: agent
- Decided by: maintainer
- Date: 2026-10-07
- Rule in: home/.agents/skills/decide/SKILL.md
- Decision: Questions are asked one at a time, except up to four independent, low-stakes questions, each with its default, which may share one message.
- Why: Trivial unrelated setup choices do not each deserve a round; dependent questions still go one by one.
- Rejected: Strictly one question per turn.
- Revisit if: grouped questions start hiding choices that depend on each other.

## D-0004: Skills keep their full guidance

- Status: Accepted
- Proposed by: maintainer
- Decided by: maintainer
- Date: 2026-10-07
- Rule in: AGENTS.md (this repository)
- Decision: Adapting a skill changes only what conflicts with the maintainer's rules (and removes em dashes); the rest of its guidance stays, whatever the length.
- Why: A skill loads only when used, so its length costs nothing otherwise; cutting guidance lowers quality.
- Rejected: Shortening skills to save tokens.
- Revisit if: a skill's description stops triggering it reliably.

## D-0005: The adapted learn skill is named tutor

- Status: Accepted
- Proposed by: agent
- Decided by: maintainer
- Date: 2026-10-07
- Rule in: claude-ai/skills/tutor
- Decision: The adaptation of Anthropic's learn skill ships as tutor.
- Why: claude.ai keeps the name learn reserved for its built-in skill even when it is turned off.
- Rejected: Replacing the built-in under the same name.
- Revisit if: claude.ai frees reserved names of disabled built-in skills.

## D-0006: MIT license, held by Nicolò Plebani (nexenne)

- Status: Accepted
- Proposed by: maintainer
- Decided by: maintainer
- Date: 2026-10-07
- Rule in: LICENSE
- Decision: Original work is MIT, Copyright (c) 2026 Nicolò Plebani (nexenne), with a LICENSE.txt in every skill. Adapted third-party work keeps its license, and the maintainer's modifications are credited (tutor: Apache 2.0 with modifications also offered under MIT).
- Why: The maintainer's standard license, compatible with reuse across his projects.
- Rejected: No license; relicensing third-party text.
- Revisit if: the setup includes third-party work whose license forbids it.

## D-0007: No AI attribution in commits

- Status: Accepted
- Proposed by: maintainer
- Decided by: maintainer
- Date: 2026-10-07
- Rule in: adapters/claude/settings.json, home/.agents/AGENTS.md
- Decision: Commits and pull requests carry no Co-Authored-By or other AI attribution; the human committer owns every line.
- Why: The maintainer's accountability policy, as in nexenne's AI_DISCLAIMER.org.
- Rejected: Tool default attribution trailers.
- Revisit if: never without a new maintainer decision.
