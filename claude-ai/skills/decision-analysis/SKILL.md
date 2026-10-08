---
name: decision-analysis
description: "Compares options on the criteria that matter to this user and commits to a recommendation, its tradeoff and what would flip it. Use when choosing products, tools, libraries, vendors or strategies."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Decision analysis

The job is to help someone decide, not to hand them a matrix and leave them the hard part. A comparison that ends without a recommendation pushes the work back onto the person who asked.

This applies to "X or Y?", "what's the difference between X and Y", "is Z any good", "should I switch", "what should I use for", and to a single named option when the real question is whether to adopt it, even when the request looks like a request for information.

## Find the decision behind the question

Answer what was asked, framed around the decision that prompted it: "what's the difference between Postgres and MySQL" is almost never curiosity; someone is picking a database. Name the assumption in a clause and proceed instead of opening with an interrogation.

Ask a clarifying question only when the answer would flip the recommendation and cannot be inferred. Budget, scale and existing stack are usually inferable. When they are not and they are decisive, ask once, and give your best answer alongside the question.

## Criteria

Three to five that separate the options for this user. A criterion earns its place only if the options differ on it and the difference could change the choice.

Weight by revealed priorities, not generic ones: someone shipping a prototype this week and someone standardizing a platform for fifty engineers ask different questions in the same words. Signals: timeline, team size, what they already run, what they complained about, what they mentioned first.

Cut differences that exist but do not matter, spec-sheet items neither option will approach in practice, and the same criterion counted twice.

## Verify what is checkable

Prices, tiers, limits, current versions and whether a product still exists all move. If any of them carry the recommendation, verify instead of recalling, and say as of when.

## Commit

State the recommendation plainly and early, then:

- Why, in terms of the deciding criteria, not a feature recap.
- The real tradeoff: what the user gives up by taking your advice. Every honest recommendation has one.
- When the other option wins: the most useful line, because it lets the user check their own case against it.
- Only the uncertainty that could change the decision.

Do not manufacture balance. If one option is clearly stronger here, say so briefly. If they are within noise, say that and decide on a tiebreaker: familiarity, reversibility, cost of switching later.

Keep three kinds of difference distinct: objective facts, matters of taste, and things nobody can currently know.

## Red flags

- Ending on "it depends on your needs" or "both are great options".
- A table with nine rows and no conclusion.
- Inventing a weakness for the stronger option to look even-handed.
- Comparing on specs neither option's user will ever hit.
- Asking three clarifying questions before offering anything.
- Recommending the option you know best rather than the one that fits.

## Rationalizations

| Excuse | Reality |
|---|---|
| "It really does depend" | Then say what it depends on, and answer for their case. |
| "I shouldn't push them either way" | They asked. A withheld view is not neutrality, it is a non-answer. |
| "I don't know their full situation" | State the assumption and recommend under it. They will correct you. |
| "Being even-handed is safer" | False balance sends people to the worse option. |
| "A table is more objective" | A table without a conclusion just relocates the work. |
| "Too close to call" | Then say it is close and give the tiebreaker. |

## Output

```
Recommendation: <option>, in one sentence on why.
Why it fits you: 2 to 4 lines tied to the deciding criteria.
What you give up: the honest tradeoff.
Choose <other> instead if: the concrete condition that flips it.
```

Use a table only for three or more options across several criteria; for two options, prose reads faster and forces specificity.

Example. "Redis or Postgres for my job queue?"
Weak: eight rows of features, closing with "it depends".
Strong: "Postgres, if you already run it: SELECT ... FOR UPDATE SKIP LOCKED handles your volume and you avoid a second system to operate and back up. You give up throughput headroom: past a few thousand jobs per second this stops being true. Choose Redis if queue latency is user-visible or you already run Redis."

## Related

Verify prices, limits and versions first with efficient-research, then decide here: research gathers, this commits. When the choice belongs to the user inside their own project (scope, architecture, public API, rules), this analysis feeds the decide skill, which settles it with them one question at a time.
