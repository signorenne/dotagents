---
name: atomic-notes
description: "Writes clear, correct notes and explanations: one idea per note, linked under a hub like a mind map. Use to write, split or reorganize notes, or to explain a topic. Not for teaching (tutor)."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne). See LICENSE.txt"
---

# Atomic notes

A reader, the user or an agent months later, should find each idea in one place, stated in its first sentence, with what makes it true, where it stops holding and how it connects to the rest. Nothing repeated, nothing padded. The method is the Zettelkasten one, and the same method shapes an explanation in chat and a set of written notes.

Three kinds of notes are kept apart. Captures (an inbox, a journal) are quick and temporary: they become notes soon or are deleted. A source note says what one source says, in your words, with its full reference; there is one per source. An idea note holds one idea in your own words, stands alone, and cites source notes rather than repeating them. This skill writes source and idea notes, and hubs.

## 1. Map before writing

List the distinct ideas the material holds, each as a sentence that states it. Order them for a reader under the topic's hub: 3 to 5 branches, prerequisites first, each branch stated as its point, not as a topic label. Up to 7 only when they are parallel items of one kind; more than that gets sub-hubs. This order is the hub's reading path, not a taxonomy: a note may sit under several hubs, and links cross branches. Note those cross-links (depends on, causes, contradicts, is an example of).

## 2. Decide what gets a note of its own

A separate concept, claim, argument, counter-argument, model, procedure or observation that other notes will link to gets its own note. A detail that only serves its parent stays a paragraph there, and a problem stays with its fix. A note passes when it is easy to name, understandable at a glance, has nothing to remove and nothing missing. A title that needs "and" is two notes, and so is a note that mixes kinds (a procedure with the analysis of why a published version fails, a concept with a case); splitting further than that only fragments the links.

## 3. Connect to what exists

When the notes go into an existing collection, search it for each idea and its neighbours before writing. An idea that already has a note extends that note (step 7) instead of getting a second one. Each new note is linked from at least one existing note besides its hub, with the reason, so it is found from where a reader already is. A hub appears when several notes cluster on a topic that has none, and every hub is reachable from the collection's entry note or index: structure grows from the links, not from a folder tree planned in advance.

## 4. Check what the notes depend on

Before writing a fact down, sort it the way efficient-research does. Facts that are numeric, version-specific, current, contested, or that the note is useless without, get confirmed against a primary source: the specification or standard, the vendor's documentation or datasheet, the reference documentation. When a fact cannot be confirmed from what you have, research it online following efficient-research, and open the page before citing it. Without search tools, mark such facts unverified and name the source to check.

- Search before you hedge: with search tools, mark a fact unverified only after looking for its primary source and not finding it, and say in your reply where you looked. Reread a source you opened before calling what it documents unconfirmed.
- Every claim is cited, attributed to the user's material, or marked as your inference.
- When a source contradicts the material, keep both with their attribution and say in Limits which holds, and for which version.
- Paraphrase; quote at most a short phrase.

## 5. Write each idea note

- Title: the idea as a claim ("CAN arbitration is bitwise and non-destructive"), unique in the collection, exactly as true as the note: it keeps the note's condition ("when", "only if") and never says more. A note that defines a term takes the term as its title; an open question takes the question. Revise title and body together until each matches the other.
- The first sentence states the idea by name. A reader who stops there has it.
- Sections, in this order, optional ones in brackets:
  - concept, claim or question: Meaning, [Mechanism and evidence], [Example], Limits, Connections, Sources;
  - procedure: When to use, [Preconditions], Steps, [Verification], Limits, Connections, Sources;
  - failure: Symptom, Cause, Fix, [Verification], Limits, Connections, Sources.
- Mechanism and evidence says why it is true or how it works, keeping what a source says apart from what you infer. Example is concrete and earns its place. Limits holds scope, versions, conditions and counterexamples.
- Connections: first the broader topic (the hub), then each related note as a link followed by one sentence naming the relation (depends on, contradicts, is an example of, is needed for). Never a bare "see also" or "related".
- Aim for 120 to 400 words of prose; code, tables, Connections and Sources do not count. Under 120, it is probably a paragraph of its parent. Over 400, apply the test of step 2: split only what fails it; a note that passes stays whole.
- Keep the numbers, units, formulas, states, field layouts and code the idea needs, trimmed to it. Leave out history, anecdotes and background the reader already has.
- Another idea is linked at its first mention, never explained again. One fact, one home: the note that owns a fact states it in full; any other note gives it at most a clause and the link.
- A note holds no remarks on how it was made ("not reread", "I checked", "not tested on this machine"); a claim's status is marked at the claim ("untested", "unverified: see <source>").
- One term per concept throughout. Define a term or an abbreviation at first use, or link its note.

Sentences and paragraphs:

- One idea per sentence, subject and verb near the start, a condition before what it conditions.
- One topic per paragraph, opening with its topic sentence; at most about 150 words.
- Active voice and present tense; verbs, not nouns made from them ("decides", not "makes a decision").
- No filler ("it is important to note", "basically", "there is", an unneeded "you can"), no hedge beyond the real uncertainty, one word where a phrase says the same, no restating the title after the first sentence.

## 6. Write the hub

- Title: the topic's name, not a claim. An old page that becomes the hub keeps its old claim title as an alias.
- Unless the collection has its own hub shape: an opening, the walk-through, then Limits, Connections and Sources.
- Open with 2 to 5 sentences: what the topic is and why it matters.
- Then walk through the branches in reading order, linking each child note at its first mention, with only the connective explanation no child owns: how the pieces fit.
- Link every child; every child names the hub as its broader topic.
- Limits holds only caveats that span several children; a caveat of one child lives in that child.

## 7. Reorganize existing notes

1. Read every page involved in full and map its ideas (step 1).
2. Each idea that earns a note (step 2) becomes one and takes its explanation, numbers and caveats with it. The old page becomes the hub and keeps its ID and file, so links to it still land.
3. Two notes on one idea become one: the unique content of the other moves in, and links to it are pointed at the survivor.
4. Keep every existing ID; a merged note's ID stays on the survivor as an alias where the format has one, otherwise every link to it is repointed first; a moved, split or merged note leaves no broken link and no orphan.
5. Account for the old text: list each fact, command, example and reference of the old page with where it went (a note, merged, or dropped as redundant), and report the dropped ones.
6. The set grows only by the hub's connective sentences, the links and new verified facts. When the new notes hold more than about one and a half times the old prose, cut repetition first.

## 8. Explain in chat

The same map, smaller:

- First sentence: the answer or the definition, with any condition that decides whether it applies at all ("If X, then Y").
- Then the parts, 3 to 5 (up to 7 when parallel), each in 1 to 3 sentences, in reading order; a list when they are parallel.
- Then the other conditions that change the answer, one line each; facts that are not conditions belong in the parts.
- When the topic is something the user works with, end with how to see or check it in practice: a command, a log line, a measurement, the usual failure and what it means.
- About 300 words for a concept, up to about 600 for a process with many steps. For more depth, go one level down the map rather than writing longer paragraphs.
- Same checking as step 4; cite looked-up facts inline. Same sentence rules as step 5.

A request to learn, understand, study or practice is teaching: use tutor instead.

## Format

Org unless the destination is Markdown (a .md file, a Markdown wiki). A vault with its own rules (an AGENTS.md, note templates, a list of note kinds, a tool that writes notes) decides file names, folders, properties, tags and section names; this skill decides content and organization. Write through the vault's tool when it has one.

In Org: a file-level property drawer with an ID, then #+title and #+filetags; links between notes are ID links; lines that start with * or #+ inside a block are escaped with a comma. Without files, as in chat, give each note as its own block, the hub first.

## Check before handing over

Each item can fail; fix what fails and check again.

- Each note holds one idea, its first sentence states it, its title is a claim (or a term, or a question), and a note outside 120 to 400 words of prose passed the test of step 2.
- Nothing is explained in two places: search the notes for each key fact and number, and cut every full statement beyond the owner's.
- Every title is exactly as true as its note; no note holds remarks on how it was made.
- Every claim is cited, attributed or marked as inference; nothing is cited from a search snippet; nothing is marked unverified without a search for it, where search tools exist.
- Connections opens with the hub, and every link names its relation in a sentence.
- Every idea of the map has exactly one home; the hub links every child and is reachable from the entry note; no note is orphaned; titles are unique.
- In an existing collection, no new note duplicates an old one, and each is linked from an existing note besides its hub.
- No paragraph over about 150 words; no filler from the list in step 5.
- A reorganized set accounts for every fact of the old page and stays within about one and a half times its prose, or says which new verified facts made it longer.
- An explanation answers in its first sentence, stays within its budget and, for something the user works with, says how to see or check it.

## Example

Material: a 1,500-word page "CAN bus" mixing arbitration, bit timing, error handling and a wiring anecdote.

Weak: the page tidied up, or split into "CAN part 1" and "CAN part 2".

Strong: the hub "CAN bus" (four sentences, then a walk-through linking each child) and three notes, "CAN arbitration is bitwise and non-destructive", "CAN bit timing divides each bit into time quanta" and "CAN error confinement moves a faulty node to bus-off", each 150 to 300 words, each opening with its statement, its bit-level numbers checked against the Bosch CAN 2.0 specification and cited, the wiring anecdote dropped and listed as dropped.

## Related

Searching itself follows efficient-research. Small fixes to an existing text follow minimal-editing. Before calling the notes correct, apply verifying-before-claiming-done.
