---
name: scoping-before-building
description: "Sizes up a request to make something (app, feature, script, doc, process) and asks only the question that changes the result before building. Use when a request is looser than what it asks for."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Scoping before building

The expensive failure is not building it wrong. It is building the wrong thing well, because the request was ambiguous and the ambiguity got resolved silently; by the time it surfaces there is a finished artifact to argue with.

The opposite failure is as real: interrogating someone who gave a clear brief. Most requests need no scoping at all. Match the process to the gap between what was asked for and what has to be decided.

## 1. Classify, before anything else

| Class | Looks like | What to do |
|---|---|---|
| Clear | Constraints given, one obvious right answer, small and reversible | Build it. State any assumption inline. No questions. |
| Bounded | One artifact, a few real unknowns, a wrong guess costs a rewrite | One question, then build. |
| Open | Multiple parts, competing approaches, or expensive to redo | Scope properly: the rest of this skill. |
| Oversized | Several independent systems in one sentence | Decompose first; do not refine details of something that needs splitting. |

Getting this wrong in either direction is a failure: treating a clear request as open wastes the user's time and reads as stalling; treating an open request as clear produces confident work aimed at the wrong target.

Signals that it is more open than it sounded: two readings would produce different artifacts; the answer depends on an audience you do not know; you are about to pick a stack, format or structure the user never mentioned; the thing has parts that could each be built separately.

## 2. Read the context you already have

Before asking anything, check what is in front of you: the conversation, uploaded files, the user's stated situation and preferences, prior work. Asking for something already provided is worse than not asking, because it shows nothing was read.

The question to ask is the one whose answer would change what you produce. Nothing else.

## 3. Ask sparingly and well

- One question at a time. A list of five is an intake form, and people answer it badly or abandon it.
- Prefer concrete choices over open prompts: "A or B?" gets a real answer; "what are your requirements?" gets a shrug. Put your recommended option first.
- Aim at purpose, audience, constraints and what "done" looks like, not implementation details you can decide yourself.
- Stop as soon as you can build something defensible. The goal is a correct first attempt, not perfect information.
- Never withhold work as leverage: give your best answer alongside the question, so a non-reply still leaves the user with something.

## 4. Offer approaches, do not just pick one

For open work, name two or three real approaches with their tradeoffs, then recommend one and say why. This earns its space only when the approaches lead to materially different artifacts and the user could reasonably prefer either. If one approach is clearly right, take it and say so in a line.

## 5. Show the shape before you build the thing

Present the design in a piece small enough to read (structure, key decisions, what is in and out of scope) and get a yes before producing the full artifact. A rejected outline costs a minute; a rejected deliverable costs the whole build and makes the user feel obliged to salvage it.

Scale this to the work: for bounded requests it is two sentences ("I'll do X with Y, leaving Z out. Sound right?"); for open work it is a short spec, in sections, with checkpoints.

## Red flags

- Picking a framework, format, tone or structure the user never mentioned, and never mentioning it either.
- "I'll build both and let them choose."
- Filling a gap with the most common answer because it is the most common.
- Asking a question whose answer would not change anything you do.
- Asking about something in a file you were given.
- A "quick thing" that has grown three sections: that is the signal to stop and re-scope, not to keep going.
- Producing the full artifact when a paragraph of shape would have caught the mismatch.

## Rationalizations

| Excuse | Reality |
|---|---|
| "I'll make reasonable assumptions" | Reasonable to you. State them out loud or they are invisible. |
| "Asking looks unhelpful" | Producing the wrong artifact confidently is what looks unhelpful. |
| "They said keep it simple, so no questions" | Simple output, not a guessed target. One question protects both. |
| "It's faster to just build it" | Faster to the first draft, slower to the right one. |
| "I can refactor later if they wanted something else" | "Something else" usually means starting over. |
| "The scope creep is fine, I'm nearly done" | Nearly done with a thing that outgrew its brief. Stop and check. |

## Handoff

Once the shape is agreed, stop scoping and build. Raising questions after approval stalls the work and makes the approval meaningless; note new questions as you hit them and raise them with the draft.

Example. "Can you build me a dashboard for our sales data?"
Weak (over-processing): eight questions about auth, hosting, roles and refresh intervals before writing anything.
Weak (under-processing): a full React dashboard with invented metrics, a chart type nobody asked for, and a data schema guessed from the word "sales".
Strong: "One thing decides this: is it for you alone, with data you paste in, or for the team on a live source? Assuming you alone and pasted data, I'd do a single page with revenue over time, top accounts and pipeline by stage. Say if the metrics are wrong and I'll build it."

## Related

When the open point is a choice that belongs to the user (scope, architecture, public API, rules), settle it with decide, one question at a time.
