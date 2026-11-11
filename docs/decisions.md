# Decision log

Owns the record of decisions behind this setup: what was decided, why, who proposed
it, who accepted it. The maintainer decides; agents add entries as Proposed and write
Accepted only for decisions the maintainer explicitly accepted or delegated ("decide"). Changed decisions get
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

- Status: Superseded by D-0013
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

## D-0013: Skills are concise and complete

- Status: Accepted
- Proposed by: maintainer (skills go straight to the point), agent (wording, guide, sources)
- Decided by: maintainer
- Date: 2026-11-07
- Rule in: docs/skill-authoring.md, AGENTS.md (this repository)
- Decision: A skill holds every step and rule a model would otherwise get wrong, each stated once; it does not explain what a capable model already knows, gives a reason only where a rule is not obvious, and keeps rare or bulky detail in a file read only when needed. Adapting a third-party skill still changes only what conflicts with the maintainer's rules. Replaces D-0004.
- Why: Anthropic's skill authoring guide: once a skill loads, every token competes with the conversation, so add only context the model lacks; its context engineering article: aim for the smallest set of high-signal tokens, which is not the same as short. Instruction adherence falls as the number of instructions grows (IFScale benchmark, 2025). D-0004's premise held only until the skill loads.
- Rejected: Keeping D-0004 (full guidance whatever the length); shortening by dropping rules (vague guidance is its own failure mode).
- Revisit if: a real session shows a trimmed skill missing a rule it needed (restore that rule), or a skill's guidance no longer fits in SKILL.md under 500 lines.

## D-0014: as-built-docs reads code on the session's model

- Status: Accepted
- Proposed by: agent
- Decided by: maintainer
- Date: 2026-11-08
- Rule in: home/.agents/skills/as-built-docs/SKILL.md (Working rules)
- Decision: The subagents that map code for as-built-docs run on the session's model (in Claude Code the general-purpose subagent), not on a smaller one.
- Why: The independent fact-check catches wrong facts but not missing ones, so a weaker reader's omissions would reach the documents unnoticed; correctness comes first and documentation runs are rare. A test run on this repository cost 6.56 USD on Opus 5.5.
- Rejected: Sonnet for the mapping subagents (cheaper, but no later step catches what it misses).
- Revisit if: a side-by-side run on the same repository shows a smaller model finds the same facts and behaviors to confirm.

## D-0015: Diagrams use the nexenne palette in day and night

- Status: Accepted
- Proposed by: maintainer (nexenne colours, no broken dark previews), agent (one file with a dark block, packages instead of stereotypes)
- Decided by: maintainer
- Date: 2026-11-08
- Rule in: home/.agents/skills/plantuml-diagrams/ (SKILL.md, palette.iuml)
- Decision: Every PlantUML diagram includes the skill's palette.iuml and no other styling: the nexenne-day colours, and the nexenne-night colours when it is drawn in dark mode. The skill names neither the palette's origin nor any project. Groups are shown with packages, not stereotypes.
- Why: A light fill set without its text colour made diagrams unreadable in the dark Emacs preview. PlantUML applies a style's dark block on -darkmode renders (tested through the picoweb server the preview uses), so one file serves both themes; styles do not reach stereotype labels, which stay small and grey.
- Rejected: No colours at all (readable but plain); fixed light colours (unreadable in dark previews); separate day and night files (the diagram would have to switch includes).
- Revisit if: the nexenne palette changes (copy its new values), or PlantUML starts writing the dark block into SVG output.

## D-0016: Skills from the case studies, checked against primary sources

- Status: Accepted
- Proposed by: maintainer (new skills from five case studies, every assumption checked online, an MVVM skill), agent (which skills, the four fixes, the Qt split, the bundled script)
- Decided by: maintainer
- Date: 2026-11-11
- Rule in: home/.agents/skills/ (parallel-agents, mechanical-changes, precise-ui-changes and its scripts/nothing_moved.py, qt-quick, clean-architecture, implement), claude-ai/skills/ (verifying-before-claiming-done, systematic-debugging)
- Decision: Five skills built from five real case studies (several agents on one repository, a refactor across many files, precise UI fixes, a live theme switch, SVG icons), each rule checked against primary sources, and five rules added to existing skills: full gates on the final commit, generated files changed at their generator, testing the current build, trusting a check script only after it catches a planted case, measuring slowness. The Qt facts and the Qt way to apply MVVM live in qt-quick, so clean-architecture stays language-neutral. precise-ui-changes bundles one tested script for its check that nothing else moved. A script a skill runs uses only the standard library plus at most one common package, and has tests that run in CI without that package (AGENTS.md, Where changes go).
- Why: The case studies are real runs that showed each need (docs/skill-authoring.md, principle 7). The sources refuted some of their claims, corrected in the skills: an SVG sourceSize multiplied by the pixel ratio counts it twice; a diff threshold of 40 let through shifts of 11 to 14 levels where the measured noise was 1; fixed time limits in the normal test suite are flaky; checks without a build only add to a build. The cost is five more skills to maintain and keep apart, and Qt facts to recheck as Qt changes.
- Rejected: one skill for Qt MVVM apps (not reusable outside Qt); precise-ui-changes without a script (the threshold mistake would recur); the case studies' claims taken unchecked.
- Revisit if: a new skill fails to trigger or misfires in real sessions, a Qt release changes the SVG or image behavior described, or the diff script misjudges a real change.

## D-0017: Every application gets every clean-architecture layer

- Status: Accepted
- Proposed by: maintainer (domain, infrastructure, repositories, DAOs and use cases, as the books describe them), agent (the recorded exception, use cases that return their results)
- Decided by: maintainer
- Date: 2026-11-11
- Rule in: home/.agents/skills/clean-architecture/SKILL.md
- Decision: Every application gets the domain, application (use cases), infrastructure (repository implementations, DAOs and data sources), presentation (view models and views) and composition root layers, with dependencies pointing inward and the repository interfaces in the domain. A use case that would only forward one call may be left out only as a decision recorded in the project's decision log. A use case returns its result; updates over time go through an output port.
- Why: The maintainer wants one structure in every project, as Martin, Evans, Fowler and Cockburn describe it. No source makes every layer mandatory (Android adds use cases "only when required", Gossman calls MVVM overkill for simple UIs, Ardalis keeps a single-project template for small apps); the recorded exception keeps the structure without use cases that only forward calls. It makes small apps heavier than they would otherwise be.
- Rejected: every layer with no exception (use cases that only forward calls); layers added only when needed, as in Android's guide (against the maintainer's structure); a domain that depends on the data layer, as in Android (against Martin, Cockburn, Vernon and the reference templates).
- Revisit if: the layers cost more than they give in a project, or projects stop following them.

## D-0018: UI threads never block; work moves through events

- Status: Accepted
- Proposed by: maintainer (an event-based architecture where the UI or graphics thread is never interrupted, file writes and heavy computation elsewhere), agent (one skill, the rules from the sources, the Qt lines in qt-quick)
- Decided by: maintainer
- Date: 2026-11-11
- Rule in: home/.agents/skills/event-driven-ui/SKILL.md, qt-quick (Threads), clean-architecture (one pointer)
- Decision: A language-neutral skill for event-based concurrency inside an application with a UI or render loop: one owning thread per piece of state, a UI thread that never waits, long-lived worker threads per role with results back as events, bounded queues with an overflow policy per stream, coalesced bursts and budgeted handling, superseded work dropped, crash-safe writes from a writer thread, injected clocks, owner checks and ThreadSanitizer. One loop with asynchronous APIs stays the answer when every handler fits the frame budget.
- Why: The maintainer's rule and fdc-next's design, which match Chromium's threading guide, Android's and Apple's main-thread rules, Qt's threading documentation, the single writer principle and the LMAX Disruptor. A separate skill loads when a UI freezes, not only for architecture questions. It brings more threads to reason about and event flows that are harder to follow in the code, hence the rule on when one loop is enough.
- Rejected: a section in clean-architecture (would not load for a frozen UI); a thread per task (switching and memory costs); locks shared between threads as the default (deadlocks and contention).
- Revisit if: in a project whose handlers all fit the frame budget the threads add only complexity, or the skill misfires in real sessions.
