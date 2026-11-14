# Writing style

Owns prose style for the docs, README text, release notes, issue text,
diagnostics and comments. The core concepts of VISION.md own the terms;
STYLE_GUIDE.md owns code comment mechanics.

## Shape

Write like a maintainer explaining the project to another engineer who wants to
build, debug or use it. Be direct, concrete and specific. Avoid marketing
language and vague praise.

Good prose answers:

- what the thing does,
- when to use it,
- what it costs,
- what it does not do,
- which file or command owns the next step.

## Punctuation

- No em dash or en dash characters in docs, comments, commits or release text.
  Use a comma, period, colon, parentheses or a plain hyphen instead.
- One sentence per idea when possible.
- Sentence case for headings. No trailing period on short headings, table
  labels or checklist items; body sentences keep their periods.
- Code markup for identifiers, commands and paths.
- A commit subject is one sentence in the form CONTRIBUTING.md gives, with no
  body. A change that needs more is split into smaller commits.

## Words to avoid

Avoid words that sound impressive but carry no engineering detail: powered by,
intelligent, smart, seamless, revolutionary, blazing fast, next-gen, unlock,
empower, leverage, streamline, enterprise-grade, world-class, best-in-class.

Avoid minimizers: simply, just, obviously, basically. If something is simple,
the reader can see it; if it is not, the word does not help.

## Structure

Lead with the problem, then the mechanism.

Bad:

> <FILL: project name> provides a powerful, next-generation toolkit.

Good:

> <FILL: one sentence that says what one component does and what it costs, in
> the project's own terms.>

## Term consistency

Use the same term every time: the one the core concepts of VISION.md give. Do
not alternate between synonyms for one thing. If a term is missing, add it there
or use a more ordinary word.

## Honesty

- Name limits directly.
- Do not promise roadmap work for code that does not exist.
- Do not hide platform, compatibility or performance limits.
- Do not turn a test gap into a confident claim.

## Ownership in docs

Structure is owned once: the docs map owns the registry, and each doc owns its
own topic. Do not scatter the same list across several files; put the canonical
list in one owner and link to it.
