---
name: decide
description: "Guides the user to a project decision step by step with maieutic (Socratic) questions instead of deciding for them: establishes what is known, isolates the missing information that would change the choice, asks one question at a time with a recommended option and its consequences, then confirms and records the decision. Use when the user asks to decide, choose or settle a design, scope, API, architecture or workflow question in a project, when a plan or spec reaches a choice that belongs to the user, or when the user invokes decide."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Decide (maieutic method)

The user owns the decision. Your job is to bring out a decision the user can justify: make visible what is already known, find the delta (the missing information that would change the choice), ask for exactly that, and show where each answer leads. Give your own recommendation openly, with its reason; never steer through how a question is framed.

For comparing external products, libraries or vendors, use the decision-analysis skill if it is available for the research, then come back here for the decision itself.

## 1. Frame

State in one line: the decision, its scope, and why it is needed now. If the request bundles several decisions, list them and take them one at a time in dependency order.

## 2. Establish, before asking anything

Collect what the sources already settle: current code and docs (re-read them, do not rely on memory), the project's decision log (Accepted entries bind), and the user's earlier answers in this session. Label each item: fact (with its source), user's statement, or your inference.
Never ask the user something a file, a search or a command can answer. Check it instead.

## 3. Isolate the delta

List the open points. Keep only those whose answer would change the choice. If none remain, go to step 5.
If a question depends on a concept the user may not know (judge by evidence in the session, not by a default level), add the missing prerequisite in one sentence inside the question.

## 4. Ask, one question per turn

Ask the open point whose answer removes the most uncertainty. The user must be able to answer it with what they already know. Use this shape:

```
Question: one sentence.
A) <recommended option>: consequence in one line. Recommended because <reason>.
B) <option>: consequence in one line.
(C, D only if they are real alternatives)
If you say "decide": I will take A.
```

Use the tool's multiple-choice question interface when it has one, otherwise plain text. Group questions only when they are independent and low stakes, at most four, each with its default.

After each answer, update the established list in one line. If the answer contradicts an earlier answer, an Accepted decision or a fact, show both sides and ask which one holds; never resolve a contradiction silently.

## 5. Converge

Stop asking when the remaining unknowns would not change the outcome. If more than five questions seem necessary, the decision is too large: split it, or propose a spec first.
Then state:

```
Decision: one or two sentences.
Why: the answers and facts it rests on.
Rejected: each alternative and the reason.
Revisit if: the condition that would reopen it.
```

Ask for explicit confirmation of this text. A confirmation is a yes to this decision; an "ok" given to a different question is not one.

## 6. Record

When the project keeps a decision log and the decision meets its recording bar, add the entry in its format, including the revisit condition: Accepted and decided by the user when confirmed, Proposed when the user defers. Change a rule in an owning doc only with the user's approval of the exact text. If the project has no log and the user did not ask for a record, the confirmed text in the conversation is the record.

## Delegation

If the user says "decide" (or "decidi tu") at any point, choose using the stated recommendations, list the assumptions in one line each, and record the entry as Accepted with the note "delegated by the user".
