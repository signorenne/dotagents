---
name: context-handoff
description: "Writes a self-contained brief so work can continue in a new chat, session or model. Use for handoffs, catch-up notes, status recaps, a prompt to continue, or before running out of context."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Context handoff

The reader of this brief has no memory of the conversation and cannot ask follow-up questions. Everything they need to act must be on the page; everything else is noise that pushes the useful parts out of view. This applies whenever continuity is the real goal (a new chat, low context, compaction, work tomorrow, a teammate or another model), even if the word handoff never appears.

Write forward, as an instruction set, not backward, as a record of what happened.

## Include

- Objective: the end result, concrete enough that the reader could recognize completion. Not "improve the pipeline" but "cut the nightly ETL from 40 minutes to under 10 without changing the output schema".
- Current state: what exists and works, specifically enough that the reader does not rebuild it.
- Decisions that still bind, with a one-clause reason each. The reason is what stops a fresh reader from re-litigating: "Postgres, not Redis: ops won't take on a second store."
- Constraints: requirements, deadlines, style rules, technical limits, things the user said they do not want, and how the user wants to be worked with; those preferences are invisible to a fresh session and get violated in its first reply.
- Artifacts: exact file names, paths, URLs, identifiers, function and table names, versions, test data keys. Reproduce the strings exactly; an approximate file name is worse than none.
- Verify before use: code-level facts the next session will rely on (files, symbols, signatures) may change before it reads the brief. Mark them so it re-reads them before editing.
- Open questions: anything unresolved the reader will hit, including what is waiting on the user.
- Outstanding work, ordered by what should happen first, not by when it came up.
- Immediate next action: one concrete thing to do first. It is the most valuable line, because it turns a summary into momentum.

## Cut, and never cut

Cut abandoned approaches, dead-end debugging, superseded drafts, conversational back-and-forth, explanations the reader can regenerate, tangents. One exception earns its space: an approach that failed for a reason someone would otherwise retry, in one line ("tried in-process batching; died on memory, don't retry").

Never cut exact values and identifiers, unresolved issues, load-bearing assumptions, dependencies and versions, constraints, and anything the user asked for and has not received.

Compression reduces volume, not precision: drop a paragraph of narrative rather than shorten a file name or round a number.

## Red flags

- Writing chronologically ("first we tried..., then we...") instead of forward.
- Paraphrasing a file name, path or identifier from memory.
- Ending without a specific next action.
- Preserving your own explanations because they were good.
- Dropping the user's stated preferences as "not part of the work".
- Adding a "here's your handoff" preamble the user has to delete.

## Rationalizations

| Excuse | Reality |
|---|---|
| "The next session can just ask" | It cannot. Nobody there has the answer. |
| "That detail is probably not important" | If it is an exact value, keeping it costs a few tokens. |
| "The history explains why we're here" | Decisions carry the why. Narrative does not. |
| "Shorter is better" | Precise is better. Cut narrative, not identifiers. |
| "They'll figure out what to do next" | They will pick something plausible and wrong. |

## Output

Deliver a single copy-pasteable block the user can drop into a new conversation as the first message, with nothing before or after it to strip.

```
# Continuing: <short project name>

## Objective
## Current state
## Decisions that still apply
## Constraints
## Artifacts
## Verify before use
## Open questions
## Outstanding work
## Start here
<the immediate next action>
```

Drop empty sections instead of writing "N/A". Aim for under 500 words; go longer only for precision (a config block, a schema, a set of exact identifiers). Length spent on facts is fine; length spent on narrative is not.

The test before returning it: hand only this text to someone competent who never saw the conversation. Could they take the next action correctly without guessing? Whatever they would have to guess belongs in the brief.
