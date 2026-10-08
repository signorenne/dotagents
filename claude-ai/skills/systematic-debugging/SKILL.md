---
name: systematic-debugging
description: "Diagnoses failures from evidence before any fix: reads the error, reproduces, compares with a working case, tests one hypothesis. Use for errors, failing tests or CI, crashes, hangs or wrong output."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Systematic debugging

Guessing at fixes is seductive because sometimes it works. When it does not, it leaves the code worse: changes that were not needed, the original bug still live, and a muddier picture of what is wrong. The cost is asymmetric, so diagnose first.

A fix you cannot explain is not a fix. If you cannot say why the failure happened, you do not know whether your change addressed it or just perturbed the timing.

Following the letter of this process while skipping its spirit (a token glance at the traceback, then the guess you were going to make anyway) is not following it.

## Phase 1: investigate

Propose no fix before finishing this phase.

1. Read the actual error: full message, exception type, innermost frame, line numbers. The exact words matter: "undefined is not a function" and "cannot read property of undefined" point at different mistakes. Errors often contain the answer.
2. State observed versus expected: what happens, where, how often, on what input, and what should happen. Sometimes the bug dissolves here: the code is right and the expectation was wrong.
3. Check what changed. "It worked yesterday" is a gift: recent commits, a dependency bump, a config or data change, a different environment.
4. Reproduce, or say you cannot. A reliable reproduction turns debugging from argument into experiment. Failing to reproduce is evidence too: intermittent failures point to concurrency, ordering, caching, clocks or data dependence.
5. Instrument across boundaries when the system has layers. For a multi-component failure (CI, build, deploy; API, service, database), do not guess which layer is wrong: log what enters and exits each boundary, run once, and let the evidence name the failing component.
6. Trace bad values backward to where they originate, and fix there, not where they finally exploded.

## Phase 2: compare with something that works

Find the nearest working case: a similar call site, a passing test, the reference implementation. List every difference, including the ones that "can't matter"; that is usually where it is. When following a reference pattern, read it completely instead of adapting from a skim.

## Phase 3: hypothesize and test

State one hypothesis: "X is the root cause because Y." It must explain all the evidence, including why the neighboring case works; a hypothesis that explains the error but not the neighbor's success is usually wrong.

Test it before fixing (a log line, a breakpoint, a one-off script, a narrowed test), changing one variable at a time. When you need evidence the user has, ask for it with one specific request ("what is the full traceback above that line?"); it is worth more than three speculative fixes. If you do not understand something, say so instead of filling the gap with a confident guess.

## Phase 4: fix and verify

Make the minimum change that addresses the root cause. Verify the original failure is gone by the same means that showed it, then check the obvious neighbors: other call sites, the same pattern elsewhere.

Count your attempts. If a fix does not work, return to Phase 1 with the new information instead of stacking another fix. After two failed fixes, stop fixing: restate your assumptions and the evidence, and change approach. When each fix reveals a new problem somewhere else, that is the signature of a wrong design, not a wrong line: say so and discuss the structure.

## Red flags: stop and return to Phase 1

- "Quick fix now, investigate later."
- "Just try changing X and see."
- "It's probably X, let me fix that."
- "I'll change these three things and run it."
- "I don't fully understand this but it might work."
- "The reference is long, I'll adapt the gist."
- "One more attempt", after two failed ones.
- Listing candidate fixes before tracing the data flow.

The user signals the same when they say: "stop guessing", "is that actually happening?", "will that even show us anything?", "are we stuck?"

## Rationalizations

| Excuse | Reality |
|---|---|
| "It's simple, skip the process" | Simple bugs have root causes too, and the process is fast on them. |
| "Emergency, no time to investigate" | Diagnosis is faster than guess-and-check thrashing. |
| "Try this first, then investigate" | The first fix sets the pattern for the whole session. |
| "Multiple changes at once save time" | If it starts working you learned nothing and carry changes you did not need. |
| "I can see the problem" | Seeing the symptom is not understanding the cause. |
| "I'll just add a retry or a try/except" | That hides the current bug and the next one. |
| "One more fix attempt" (after two) | Repeated failure means the model of the problem is wrong. |

## Symptom patches to refuse

Swallowing the exception, wrapping a race in a retry, special-casing the input that crashed, defaulting a key that was legitimately missing, broad defensive try/except with no failure mode in mind. Each turns a loud bug into a silent one.

## Output

1. Root cause: what is wrong, in a sentence or two, with the evidence that establishes it.
2. Fix: as small as it can be.
3. Verification: how it was confirmed, or how to confirm it.
4. Remaining uncertainty, only if material (for example "this fits the traceback but I couldn't reproduce it locally").

Keep narration short. Say "likely" when it is likely.

Example: an intermittent KeyError: 'user_id' in a request handler.
Weak: replace the lookup with a default value; now it silently returns wrong data.
Strong: the key is absent only on requests that bypass the session middleware, which is why it happens on the health-check path: that route is registered outside the middleware stack. Register it inside, or exclude the path in the handler. Reproduced on demand by calling /health.

## Related

Once the cause is established, apply the fix with minimal-editing. Before saying it is fixed, apply verifying-before-claiming-done.
