---
name: efficient-research
description: "Decides when to search and how much, prefers primary sources, and labels what is sourced, inferred or unknown. Use when an answer depends on current, changeable or contested facts."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Efficient research

Two failure modes cost real money: answering a changeable question from memory, and burning ten searches on something one good source settles. This skill is the narrow band between them.

Before any search ask: would being wrong here matter, and could the truth have changed since I last saw it? If both are yes, search. If either is no, answer directly.

Confidence about a changeable fact is not evidence. The more familiar the domain, the more certain the stale answer feels.

## Sort the claims first

- Timeless or structural (how TCP works, what a P/E ratio means, historical dates): answer from knowledge.
- Changeable (versions, prices, availability, who holds a role, current law, what exists now): always verify.
- Consequential and specific (a number going into a deck, a dosage, a legal deadline, a config flag headed for production): verify even when fairly sure.
- Load-bearing (the recommendation collapses if this one fact is wrong): it needs a source.

Only the last three get searched. This applies even when the user never says search or sources, and even when the question feels like settled knowledge ("is X still true", "what's the best Y right now").

## Budget

| Question shape | Typical searches | Stop when |
|---|---|---|
| Single current fact | 1 to 2 | An authoritative source states it |
| Comparison of 2 to 4 known things | 3 to 6 | Each has a primary source for the deciding specs |
| "What are my options" | 4 to 8 | New queries return names you already have |
| Contested, evolving or multi-part | 8 to 20 | Every sub-claim is grounded and disagreements are resolved or characterized |

Search each named entity separately: a combined query returns shallow results for all of them.

## Source priority

1. Primary and official: the vendor's docs, the filing, the statute, the dataset.
2. Original research, standards, specifications.
3. High-quality independent reporting or specialist analysis.
4. Aggregators: use them to find primaries, not as the citation.
5. Community evidence: legitimate when lived experience or real-world reliability is the actual question.

Prefer one source that answers several open questions over several that each answer one.

## Stop, and keep going

Stop when an authoritative source states the claim and nothing credible contradicts it, when queries return the same sources, or when the remaining uncertainty is something searching cannot resolve (then say so).

Keep going when strong sources materially disagree, when the only support is an aggregator quoting someone unnamed, when the source predates a known change, or when you have general context but not the specific detail asked about.

## Dates

Time is where research quietly goes wrong. Distinguish the publication date, the event date and the date of the fact itself; a recently updated page can hold stale figures, so check the figure's own date. Use the real current date in queries. Flag age when it is the best you have: "the most recent figure I can find is from 2024."

## Conflict

When credible sources disagree, do not average them or silently pick one. Say what each claims, prefer the one closer to the fact's origin, and note whether the disagreement changes the answer; if it does not, one clause is enough.

## Red flags

- Rewording a query you already ran, hoping for different results.
- Opening a fifth source when three agreed.
- Reaching for a number you remember instead of one you retrieved.
- Citing a listicle or content farm because it was the top result.
- Answering "what's the current X" without checking anything.
- Padding the answer with sources that did not change it.

## Rationalizations

| Excuse | Reality |
|---|---|
| "I know this one" | You knew it as of training. Prices, versions and roles move. |
| "One more search to be thorough" | Thoroughness is coverage of the claims, not query count. |
| "The user didn't ask for sources" | They asked for a correct answer. |
| "Close enough for a rough figure" | Rough figures get pasted into decks as exact ones. |
| "No time to verify" | A wrong current fact costs more time than the search. |
| "Lots of sources say it" | Aggregators copy each other. Find the origin. |

## Output

Lead with the answer. Then only what earns its place: evidence that carries weight, uncertainty that could change the conclusion, and the implication for the user's decision. Cite what a skeptic would click. When it changes how much to trust a key claim, name the evidence type (meta-analysis, randomized trial, observational study, preprint, benchmark, vendor documentation).

No search diary: "I searched for X, then Y" is process, not information, unless the user asked how you found it. Never present a source as read if you saw only a snippet.

Label the status of each part: what a source says, what you infer, what is unknown. That labeling is the most useful thing in a research answer and the first to get lost.

Example. "Is the Pro plan still $20/month and does it include the API?"
Weak: three searches, a hedged paragraph, a summary of the pricing page.
Strong: one fetch of the official pricing page, then "Yes, $20/month as of the pricing page today. API access isn't included; it is billed separately per token." Two facts, one primary source, done.

## Related

If the research feeds a choice, hand the verified facts to decision-analysis and commit there. Before presenting findings as settled, apply verifying-before-claiming-done.
