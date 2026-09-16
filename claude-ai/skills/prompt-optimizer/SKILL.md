---
name: prompt-optimizer
description: "Rewrites prompts and AI instructions to be specific, checkable and free of filler, keeping examples and real constraints. Use when writing or debugging a prompt, system prompt, agent or skill."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Prompt optimizer

A prompt is a specification, and the failure mode is not length but ambiguity. Most bloated prompts are bloated and vague: paragraphs of emphasis wrapped around an underspecified task. Cutting the emphasis and sharpening the spec are the same edit.

This applies to anything that is itself an instruction for an AI model: prompts, system prompts, custom instructions, agent or subagent instructions, skills, templates, and "why does it keep doing Y instead of Z", even when the user only pastes text and says "make this better".

Optimize the total tokens and turns needed to reach a good result, not the length of the first message. A prompt fifty words longer that avoids two rounds of correction is the shorter prompt.

## Preserve

- The objective, concrete enough to be checkable.
- Context the model cannot infer: domain facts, audience, prior decisions, what was already tried.
- Real constraints: format, length, tone, what to avoid, technical limits.
- The required output shape.
- Success criteria, when "good" is not obvious from the task.
- Examples. If the original has good ones, keep them; they do more work per token than any instruction.

## Cut

- Repeated instructions and duplicated constraints.
- Motivational filler ("this is very important", "take a deep breath", "you are the world's best..."). Flattery and stakes inflation do not improve output.
- Role-play framing the task already implies.
- Blanket instructions to think deeply, be thorough, or use every available tool.
- Threats, all-caps insistence, stacked emphasis. State a rule once and say why: reasons generalize to cases the rule did not anticipate; bare rules do not.
- Instructions implied by the task ("write in complete sentences" on an essay prompt).
- Defensive handling for edge cases that will not occur.

## Sharpen

The highest-value edit is usually replacing a vague instruction with a checkable one:

| Vague | Checkable |
|---|---|
| "Be concise" | "Under 200 words." |
| "Make it professional" | "Neutral register, no exclamation marks, suitable for a client email." |
| "Handle errors properly" | "On 4xx return status and message; on 5xx retry twice, then fail loudly." |
| "Use good sources" | "Cite primary sources; no content farms." |
| "Think about the audience" | "Audience: our CFO, non-technical." |

If a constraint cannot be made checkable, it is decoration.

## Structure

Simple task: plain natural language, one paragraph. Structure adds overhead and reads as ceremony when the task does not need it.

Complex or repeated task: label the parts so they can be edited independently:

```
Objective
Context
Constraints
Output format
Success criteria
```

Add tags or delimiters only where they cut real ambiguity, most usefully to separate instructions from pasted data. Put long reference material before the instructions and the task last; that order is more reliable than the reverse. Write the prompt in the style you want back: a prompt full of markdown invites markdown.

A system prompt holds standing rules that apply to every request, with no task in it; a one-shot prompt holds everything. Mixing the two is why system prompts drift toward bloat.

## Debugging a prompt that misbehaves

When the user says "it keeps doing X", find the instruction that permits X, not a new instruction forbidding it. Prompts fail more often from a vague clause the model resolved badly than from a missing rule; adding "DO NOT do X" on top of the clause that invited X gives a longer prompt with the same behavior.

## Red flags

- Adding a rule instead of fixing the clause that caused the problem.
- Making it shorter while making it more ambiguous.
- Keeping emphasis you cannot justify ("it says IMPORTANT, better leave it").
- Stripping examples to save tokens.
- Restructuring a three-line prompt into five labeled sections.

## Rationalizations

| Excuse | Reality |
|---|---|
| "Emphasis makes it comply" | Emphasis competes with emphasis. Specificity works; volume does not. |
| "More instructions, more control" | More instructions, more conflicts the model resolves for you. |
| "Shorter is always better" | Shorter and vaguer costs more in correction turns. |
| "The role-play framing sets the tone" | The task sets the tone. The persona is usually inert. |
| "Better safe than sorry on edge cases" | Unreachable branches dilute the reachable ones. |

## Output

Return the optimized prompt as a single copy-pasteable block with nothing to strip out. If the changes are not obvious, add two or three lines on what you cut and why, not a full diff.

If the original is ambiguous in a way you cannot resolve, do not guess silently: write it on your best reading, then flag the assumption in one line.

Example.
Before: "You are an expert senior data analyst with 20 years of experience. It is EXTREMELY IMPORTANT that you think very carefully and deeply about this. Please analyze the attached sales data thoroughly and give me a really good comprehensive analysis. Take your time. Be accurate!!!"
After: "Analyze the attached sales CSV. Identify the three largest drivers of the Q3 revenue change versus Q2, quantify each, and note any data-quality issues that affect confidence. Output: a short paragraph per driver, then a one-line bottom line. Audience: our CFO."

Barely shorter, but better, because every line now specifies something the model would otherwise guess.
