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

## D-0008: Every skill loads locally from the repository

- Status: Accepted
- Proposed by: maintainer (every skill local), agent (synced copies turned off)
- Decided by: maintainer
- Date: 2026-10-07
- Rule in: install.py, claude-ai/README.md
- Decision: install.py links every skill of the repository, the claude.ai set included, into each local agent. In Claude Code it turns off the copies of the same skills synced from claude.ai (skillOverrides; a value set by hand wins), so each skill loads once, from the repository. Changes reach claude.ai by uploading the built zip.
- Why: One version to edit and test locally before it reaches claude.ai. Claude Code lists a synced skill next to a local skill of the same name instead of replacing it.
- Rejected: Relying on claude.ai sync for the claude.ai set in Claude Code (missing where sync does not run, stale until uploaded); keeping both copies listed.
- Revisit if: Claude Code lets a local skill replace a synced skill of the same name.

## D-0009: Implementation keeps a progress log with the author of every decision

- Status: Accepted
- Proposed by: agent
- Decided by: maintainer
- Date: 2026-10-09
- Rule in: home/.agents/skills/implement/SKILL.md, project-setup templates (agent workflows)
- Decision: implement writes .private/progress/<slug> during the work: each step with its commit and check, and each decision as it is taken, marked by the maintainer or by the agent, with the reason and the alternative not taken. Agent decisions stay Review: pending until the maintainer keeps or changes them; those that meet the decision log's bar also go there as Proposed.
- Why: The maintainer reviews every choice, his and the agent's, in one place, and a later session resumes from facts instead of memory.
- Rejected: Progress only in commits and the final handoff (agent decisions scattered, nothing between steps if a session dies).
- Revisit if: the log duplicates what commits and the decision log already show.

## D-0010: Refute before you rely is the core method of every agent

- Status: Accepted
- Proposed by: maintainer (Socratic core, recording refuted assumptions, lessons as proposed rules, checking the maintainer's premises), agent (checks over rereading, placement and wording)
- Decided by: maintainer
- Date: 2026-10-30
- Rule in: home/.agents/AGENTS.md (Refute before you rely); implement, spec, decide, review and session-close skills; home/.agents/agents/reviewer.md; claude-ai/skills/context-handoff
- Decision: Every agent treats each claim its work depends on (its own, the maintainer's factual premises, a document's, a subagent's, a test's) as a hypothesis and tries to break the ones that would change the result with the cheapest check that could fail; rereading its own reasoning is not a check. Refuted assumptions go into the progress log and the handoff, and session-close drafts a rule change for each one a rule, a skill or a subagent instruction should have prevented. The rule lives in the always-loaded global instructions (about 2 KB, roughly 500 tokens per session); the workflow skills and the reviewer apply it at fixed points.
- Why: Every problem caught on feat/workflow-upgrade came from an external check or an independent agent, never from rereading; a method that loads only when triggered would be absent when an unexamined assumption slips through.
- Rejected: A standalone challenge skill on top (overlaps reviewer and spec verification; without subagents the author attacks its own work); a skill only (acts only when triggered); self-refutation with no record, no lessons and no premise checks.
- Revisit if: the global instructions approach the 200-line limit, or sessions show over-questioning or checks that do not change outcomes.

## D-0011: Tests are written by the implementer and attacked by the reviewer

- Status: Accepted
- Proposed by: maintainer (a test skill against false positives, its name), agent (author and attack model, test edit rule)
- Decided by: maintainer
- Date: 2026-10-30
- Rule in: claude-ai/skills/trustworthy-tests/SKILL.md, home/.agents/AGENTS.md (Agentic work), home/.agents/skills/implement/SKILL.md, home/.agents/agents/reviewer.md
- Decision: The trustworthy-tests skill (claude.ai set, installed for every agent) covers every automated test, unit tests first. The implementing agent writes each test first and sees it fail for the right reason; the reviewer, in a fresh context, names a wrong implementation or mutation that would still pass each new or changed test. An existing test's expected value changes only with cited evidence from the spec, the docs or a fact established independently of the code under test; deleting, skipping or loosening a test needs the maintainer's approval, except deleting the test of a behavior an approved spec or plan removes.
- Why: An independent attack on every test with no extra agent per step and one flow in all five tools; clearly wrong values get fixed without an interruption while weakening stays blocked.
- Rejected: A fresh agent writing tests from the spec before implementation (an extra agent per step, loops when tests do not fit the real interface, only where subagents exist); approval for every test change (more interruptions); unit tests only (implement's test-first step is often an integration test); local-only placement (no test help in claude.ai chat).
- Revisit if: reviews keep finding false-positive tests that passed the implementer's failing-run check, or misreadings of the spec end up encoded in tests.

## D-0012: Stop and report only when a refuted claim changes the plan

- Status: Accepted
- Proposed by: agent (from the third review of the socratic core work)
- Decided by: maintainer
- Date: 2026-10-30
- Rule in: home/.agents/AGENTS.md (Refute before you rely; Grounding in the current state)
- Decision: A refuted claim, or a difference between reality and memory or a document, stops the work for a report only when it changes the plan, a requirement or a decision. Any other refuted assumption is corrected and recorded; any other difference is corrected and named.
- Why: Grounding stopped on every difference from memory or a document, and the Refute section sent refuted claims from those sources to the same stop, so a slip in the agent's own recollection, or a stale detail no step relies on, would interrupt routine work inside an approved plan. The maintainer still hears first about every change to what was approved.
- Rejected: Narrowing only the Refute sentence (it would contradict Grounding's stop on memory); a list of document types that stop (misses a refuted assumption of the agent's own that changes the plan); leaving both rules as they were.
- Revisit if: a session changes course on a refuted claim the maintainer wanted to hear about first, or sessions still stop for differences that change nothing.
