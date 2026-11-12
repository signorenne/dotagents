---
name: minimal-editing
description: "Makes the smallest change that fully satisfies an edit request and shows only what changed. Use when fixing, tweaking, rewording or refactoring an existing draft, file, config or function."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Minimal editing

When someone asks for a change to something they made, they are trusting you with work they care about. Unrequested edits break that trust in a specific way: the user now has to audit the whole artifact to find out what else you did, and that review usually costs more than the extra improvements were worth.

Make the smallest change that fully satisfies the request. Minimal does not mean partial: if the fix requires three places, change three places and say so. Rewriting more than asked and then explaining why it was an improvement is still rewriting more than asked.

## Preserve

- Everything outside the requested change, byte for byte, including whitespace, comment style and quote characters.
- The author's voice: their rhythm, vocabulary and formality. Editing prose is not an invitation to make it sound like you.
- Existing patterns: match the surrounding naming, error handling and structure even where you would have chosen differently. Consistency with the file beats consistency with your taste.
- Behavior and interfaces, unless changing them is the request.

## Do not

- Rewrite passages to make them different.
- Fold in unrelated improvements: reformatting, import sorting, tightening a nearby function.
- Refactor code you happened to read.
- Introduce abstractions for cases that do not exist.
- Add features, options or error handling nobody asked for.
- Reorganize a file to accommodate a local change.

## The escape valve

If you notice a real problem outside the scope (a bug, a security issue, a factual error), mention it in one line and let the user decide. Noticing helps; fixing it unasked does not. This one line is what makes strict scope safe, and it is the right move every time the urge to fix something extra appears.

## Rationalizations

| Excuse | Reality |
|---|---|
| "It's easier to regenerate the file" | Easier for you, costlier for them, and it silently drops things you did not notice. |

## Output

In chat, fit the shape to the change:

- Localized code change: a diff or the changed function, with enough context to place it.
- Prose edit: the revised paragraph or section.
- Several scattered changes: each one separately, labeled by location.
- Whole artifact: only when asked, or when the artifact itself is the deliverable (a document meant to be downloaded or published).

State in one line what you changed and, when it is not obvious, why. If you deliberately left alone something the user might expect you to touch, say so; silence there reads as an oversight.

Example. "The retry logic in fetch_user swallows the exception, can you fix that?"
Weak: the whole module back, with the retry fixed, type hints added, imports sorted and fetch_order refactored to match.
Strong: the four changed lines, re-raising the exception after the final attempt; a note that the log call was left alone because it is the only trace of earlier attempts; one line saying fetch_order has the same bug if they want it fixed.

## Related

If the change fixes a failure, diagnose it first with systematic-debugging, then change only what the diagnosis implicates.
