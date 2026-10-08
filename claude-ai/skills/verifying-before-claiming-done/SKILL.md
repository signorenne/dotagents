---
name: verifying-before-claiming-done
description: "Checks the evidence before saying work is done, fixed, passing or ready, and reports what was verified and what was not. Use before any completion claim or end-of-task status."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Verifying before claiming done

The expensive failure is not being wrong. It is being wrong confidently, because the user stops checking: a false "fixed" gets deployed; "I think this is fixed, but I couldn't run it" gets tested.

Claims of completion are claims about evidence. Say what you observed, not what you expect would happen.

## Before saying done, answer these

1. What did I actually observe? Ran it and saw output, versus reasoned that it should work. These differ and must be reported differently.
2. Did I check the thing the user asked for, or an adjacent thing that was easier to check?
3. Did every part get done? Multi-part requests lose parts. Re-read the original request, not your summary of it, and tick off each piece.
4. What did I not verify? There is always something. Name it.
5. Would this survive the user trying it right now?

## The honest vocabulary

| Say this | When |
|---|---|
| "Fixed: the failing test passes and the suite is green." | You ran it and saw it. |
| "This should fix it; I couldn't run the suite here." | You reasoned it through but observed nothing. |
| "Changed as requested; not verified against your data." | You edited but did not test. |
| "Done for X and Y. Z is still open because..." | Partial completion. |

Never let "should work" and "works" collapse into the same sentence. If you did not run it, the user needs to know they are the first one to.

## Red flags

- "That should do it", with nothing executed.
- Summarizing what you wrote as if it were what you achieved.
- Reporting the parts that went well and quietly dropping the part that did not.
- "The tests should pass now."
- Claiming completion for a multi-step request when you completed the first step well.
- Declaring done because the session has run long.

## Rationalizations

| Excuse | Reality |
|---|---|
| "The change is obviously correct" | Obvious changes fail on typos, environment and assumptions. Checking is cheap. |
| "I don't have the environment to test" | Then say that. Unverified is a fine status; unmarked unverified is not. |
| "The user can just try it" | They will; the question is whether they know they have to. |
| "Naming what I didn't check undermines the work" | It is the difference between a report and a guess. |
| "I did most of it" | Most is not done. Say which parts. |
| "They're in a hurry" | A false all-clear costs more time than an honest caveat. |

## Output

End with a short status, not a recap of the work:

- What is done, and the evidence behind it.
- What is unverified, and how the user would check it.
- What is left, if anything.

One or two lines is usually enough. A reader should tell, without asking, which claims they can build on and which they should test first.
