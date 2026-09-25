---
name: architecture-doc
description: "Builds a requirements document and an architecture document with the user for a new system or major component, following established practice: EARS requirements checked against ISO/IEC/IEEE 29148, quality scenarios covering ISO/IEC 25010, an arc42 architecture with C4 diagrams, ADRs, traceability, an ATAM-style evaluation and an independent review. Use when the user plans a new system, product or major component, or asks for its requirements (functional or non-functional), an SRS, an architecture document, arc42 or C4 diagrams, or an evaluation of a planned architecture. Not for a single decision (decide), one increment of an existing repository (spec) or documenting existing code (as-built-docs)."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Architecture doc

Goal: two clear documents a team can build from: REQUIREMENTS.md (what the system must do, and how well) and ARCHITECTURE.md (how, and why).

Sources, cited in the documents where used: ISO/IEC/IEEE 29148 (requirements); EARS (Mavin et al., 2009); ISO/IEC 25010:2023 (quality model); Bass, Clements, Kazman, Software Architecture in Practice (quality scenarios, tactics, ATAM); ISO/IEC/IEEE 42010 (stakeholders, concerns, views); arc42; the C4 model; Nygard's ADRs (with the rejected options that later templates such as MADR add); Fairbanks, Just Enough Software Architecture (design depth by risk); Ford, Parsons, Kua, Building Evolutionary Architectures (fitness functions).

## Working rules

- The user owns requirements and decisions. Ask one question at a time with your recommended answer; use the decide skill for choices between options.
- Never invent a requirement or a number. Your proposals stay "proposed" until the user confirms them; an unknown number is written "assumed: <value>, to confirm" and listed in the open questions.
- Write the documents as you go and keep the open questions in them, not in the chat.
- Spend detail where a mistake is expensive or hard to undo (data, interfaces, distribution, security, top quality scenarios); keep the rest short.
- Check what a technology can do in its documentation and cite it.
- For an existing codebase, have scout map it, and describe the current and the target state separately.
- Use the project's docs folder and format (default REQUIREMENTS.md, ARCHITECTURE.md, diagrams/). The architecture links requirements by id and never copies them.

## Keep the documents easy to read

- Plain words, short sentences, one idea per sentence. Every term in the glossary, used with one meaning.
- Each document opens with a short summary: the problem, the main decisions, the top risks.
- Use a table or a diagram when the content has structure. Each diagram answers one question, has a title and a legend, and shows only what that question needs; use the tool's default look, with no style file, theme or colors, so it stays readable in light and dark viewers.
- No padding: drop a section that adds nothing, with a one-line reason.

## 1. Frame

The problem and who has it; the business goals and how success is measured; what is in and out of scope.

## 2. Stakeholders and concerns

Table of role and concerns. Include operations, support, security, compliance, maintainers and integrators. Every concern must end up covered by a requirement, a constraint or a section, or listed as out of scope.

## 3. Context, constraints, assumptions

- Context: the system as one box with the people and systems around it (C4 context diagram); for each interface, what flows, in which direction, over which protocol, and who owns the contract.
- Constraints: decisions already made elsewhere (technology, budget, deadline, regulation, the team's size and skills), each with its source.
- Assumptions: what you take as true, and what changes if it is false.

## 4. Functional requirements

One EARS sentence each:

| Pattern | Form |
|---|---|
| Ubiquitous | The <system> shall <response>. |
| Event-driven | When <trigger>, the <system> shall <response>. |
| State-driven | While <state>, the <system> shall <response>. |
| Unwanted behavior | If <condition>, then the <system> shall <response>. |
| Optional feature | Where <feature is included>, the <system> shall <response>. |
| Complex | While <state>, when <trigger>, the <system> shall <response>. |

- Write the failure cases on purpose (invalid input, timeout, lost connection, concurrent edits): that is where systems break.
- Each requirement has: id (FR-01, never reused), statement, rationale, source, priority (must, should, could, won't), verification (test, analysis, inspection or demonstration) with its acceptance criterion, status.
- Check each against the 29148 characteristics: necessary, appropriate, unambiguous, complete, singular, feasible, verifiable, correct, conforming. Replace vague words (fast, user-friendly, robust, flexible, intuitive) with a measure.

## 5. Quality requirements

- Go through the nine ISO/IEC 25010:2023 characteristics: functional suitability, performance efficiency, compatibility, interaction capability, reliability, security, maintainability, flexibility, safety. Write requirements for those that matter; say in one line why the others do not.
- Write each as a quality scenario (QS-01): source, stimulus, artifact, environment, response, response measure (a number with a unit). Example: a user submits a search to the search service at a peak of 200 requests per second; results return within 300 ms at the 95th percentile.
- Rate each scenario high, medium or low for business importance and for technical risk (utility tree). High on both means architecturally significant: these drive the design and the evaluation.
- Then show the user the requirements summary and the open questions, and wait for the go before designing: a design built on unconfirmed requirements gets rebuilt.

## 6. Architecture (arc42)

1. Introduction and goals: link to the requirements; the top 3 to 5 quality goals.
2. Constraints: link, plus technical constraints found during design.
3. Context and scope: business and technical context.
4. Solution strategy: the few fundamental decisions, each linked to the scenarios it serves, with the tactics chosen for each top scenario (for example redundancy and retries for availability, caching for performance, information hiding for modifiability) and what each costs. For a queue or a retried call, state the delivery guarantee and how the receiver handles duplicates and reordering.
5. Building blocks: C4 container diagram, component diagrams where useful. For each element: responsibility in one sentence, interfaces, data it owns, requirements it realizes.
6. Runtime: the key flows as sequence diagrams, including at least one failure flow.
7. Deployment: nodes, environments, scaling, failover. Size it with an estimate computed by a command from confirmed or assumed inputs (peak requests per second, data volume and its yearly growth), and name the component that reaches its limit first and at what load; that load is the revisit condition of the decisions it strains.
8. Crosscutting concepts that apply: domain model, persistence, error handling, security, observability, configuration.
9. Decisions: when the project has a decision log, record each decision there and list them here by id, one line each; otherwise one ADR each here (title, status, context, decision, consequences, rejected options, revisit condition), numbered and never deleted, a superseded ADR linking to its replacement.
10. Quality: for each scenario, the decisions that address it, and a fitness function (an automated check that fails when the design drifts) where possible.
11. Risks and technical debt, by priority, with mitigation.
12. Glossary.

## 7. Traceability

A matrix of requirement, building blocks, decisions and verification. Flag a requirement with no building block, a building block with no requirement, a top scenario with no decision, and a requirement with no verification.

## 8. Evaluate (ATAM style)

Walk each significant scenario through the design and record sensitivity points, tradeoff points, risks and non-risks. Then attack it: each dependency slow, down or returning garbage; each data store at ten times the volume; each interface with a malicious caller. A risk goes to arc42 section 11 or changes the design; changing a decision the user accepted goes back to the user.

## 9. Independent review

Give both documents, without your reasoning, to a subagent that did not write them (in Claude Code the general-purpose subagent told not to edit; elsewhere the reviewer, told to review the documents, not the branch diff; it has no web access, so check the facts about technologies against their documentation yourself). It reports by id: requirements that fail a 29148 characteristic, conflicts, concerns not covered, missing or vague measures, traceability gaps, wrong facts about a technology, contradictions between the documents, and passages hard to understand. Re-check each finding before fixing it; show the user any change to a confirmed requirement or an accepted decision.

## 10. Report

Document paths, decisions (taken by the user or by you), open questions, top risks, what was verified. Propose the build order, riskiest first (a walking skeleton or a spike), each step ready for the spec skill.
