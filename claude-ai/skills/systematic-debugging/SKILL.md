---
name: systematic-debugging
description: "Diagnoses failures from evidence before any fix: reproduces, compares with a working case, tests one hypothesis. Use for errors, failing tests or CI, crashes, hangs, slowness or wrong output."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Systematic debugging

Diagnose before you change anything. A change made without knowing the cause either misses it or hides it, and each miss leaves edits behind that blur the next attempt. Diagnosis is done when you can say why the failure happens and why the nearby cases do not fail.

## 1. Collect the evidence

Propose no fix in this step.

- Read the whole error: message, type, the innermost frame of your own code, line numbers. The wording carries information: in JavaScript, "x is not a function" and "Cannot read properties of undefined (reading 'x')" are different mistakes.
- For a failing CI job, save the failed job's log to a file with the CI's command-line tool (on GitHub: gh run view <run-id> --log-failed) and read around the first error; without such a tool, ask the user for that part of the log.
- Write down what happens and what should happen: the input, the place, how often. Sometimes the expectation turns out to be the mistake.
- Look at what changed since it last worked: commits, dependency versions, configuration, data, environment.
- Make it fail on demand, or record that you could not: a failure that comes and goes points at timing, ordering, caching, clocks or data.
- In a system of several parts (CI, build and deploy; client, service and database), record what crosses each boundary during one run, so the run shows which part goes wrong instead of a guess.
- Follow a bad value back to where it is first produced; the fix belongs there, not where it surfaced.

## 2. Compare with a case that works

Find the closest thing that works: another caller, a passing test, a reference implementation, the previous release. Write down every difference between the two, including the ones that look irrelevant. When a reference is the model, read all of it.

## 3. One hypothesis, tested

Name a single cause and the evidence for it in one sentence ("the cache returns the old entry because its key ignores the locale"). It has to account for everything you collected, including why the working case works. Test it with the smallest probe (a log line, a breakpoint, a narrowed test, a short script), changing one thing at a time. If evidence only the user has would settle it, ask for that one item. Where you do not understand something, say so.

## 4. Fix the cause and prove it

- In a project with tests, first add a test that reproduces the failure and watch it fail for this reason (trustworthy-tests).
- Change as little as the cause needs. Show that the original failure is gone by the same means that showed it, then look for the same pattern elsewhere.
- A fix that does not work sends you back to step 1 with what it taught you; do not stack a second fix on it. After two failed fixes, stop and restate the evidence and your assumptions. When each fix moves the problem somewhere else, the design is wrong rather than a line: say so.

## Slowness

Slowness is a failure like any other: a plausible cause is a hypothesis until a measurement names it.

- Measure where the time goes before changing any structure: a timeline or frame trace (an on-CPU profiler misses time spent waiting on I/O or locks), and the longest single call or frame, on a release build.
- Time on an otherwise idle machine, over several runs, and compare medians: a parallel build or another job can slow a measurement several times.
- Pin the fix with a test of the cause (no image decode on the UI thread, a count of calls or allocations). A wall-clock limit belongs in a separate performance job with repeated runs: in the normal test suite it fails whenever the machine is busy.
- When the cause is work blocking the UI or render thread, move it with the event-driven-ui skill where available.

## Signs you are guessing

Go back to step 1 when you catch yourself planning to investigate after the fix, changing something to see what happens, changing several things in one run, fixing a cause you cannot explain, working from a skim of a reference, or listing fixes before tracing where the bad value comes from. The user is saying the same when they ask whether something is really happening or say the work is going in circles.

## Fixes that hide the bug

Do not swallow the exception, retry around a race, special-case the input that crashed, default a value that was missing for a reason, or wrap code in a broad try/except with no failure in mind. Each turns a visible failure into a silent one.

## Output

1. Cause: what is wrong, in one or two sentences, with the evidence that shows it.
2. Fix: as small as the cause allows.
3. Verification: how it was confirmed, or how to confirm it.
4. What is still uncertain, only when it matters (for example "this fits the traceback, but I could not reproduce it locally").

Say "likely" when it is likely, and keep the narration short.

Example: an intermittent KeyError: 'user_id' in a request handler.
Weak: replace the lookup with a default value, so the handler now returns wrong data without an error.
Strong: the key is missing only on requests that skip the session middleware, which is why it happens on the health-check path: that route is registered outside the middleware stack. Register it inside, or exclude the path in the handler. Reproduced on demand by calling /health.

## Related

Once the cause is established, apply the fix with minimal-editing. Before saying it is fixed, apply verifying-before-claiming-done.
