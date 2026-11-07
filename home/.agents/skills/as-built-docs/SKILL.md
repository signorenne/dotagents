---
name: as-built-docs
description: "Writes as-built documentation of an existing repository or app from its code: a knowledge base for non-developers, a manual test guide, a developer guide and diagrams, every statement traced to code or a spec and independently fact-checked. Use when the user asks to document a repository or app (knowledge base, test guide, developer guide, onboarding docs or architecture docs of existing code, DeepWiki-style docs), or to update such docs after the code changed."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# As-built docs

Goal: docs that describe the software as built at one commit, where every statement comes from code or a spec you read. Readers act on docs without checking them, so a wrong statement is worse than a missing one.

## Working rules

- Keep facts in a notes file (.private/as-built/notes.md when .private/ is git-ignored, otherwise a scratch folder), one line each: id, area tag, statement, file:line. Write chapters from the notes: they survive compaction and spare rereading the code.
- Delegate code reading to scout, one per area, returning facts in that line format. Send long command output to gate-runner.
- External value: a named value the software exchanges with another system (message or signal field, API parameter, configuration key, file field), defined in a contract (API spec, schema, message database) owned by whoever maintains that definition.
- Write one document and one chapter at a time.
- Describe as built: never fix the code in the text. Suspicious behavior goes in "behaviors to confirm"; the owner decides what is a bug.

## 1. Inputs

Take them from the request, the repository and its existing docs; ask only what none of them settles.

- Code path, docs folder, file names, language, markup and conventions (match the existing docs).
- Documents: by default knowledge base, test guide, developer guide, diagrams. Drop one that has no reader (a library has no manual test guide).
- Docs of a sibling project, if given: copy their structure, never their content.
- Where the external contracts are defined (API specs, schemas, protocol databases): the names in the code are only half of each contract.
- The commit and versions described, each with its source.
- Existing docs that record a commit: go to section 7.

## 2. Map the code

Note, with file:line:

- features, states, what is saved and restored, startup, timers, limits, defaults;
- every surface actually registered (screens, commands, endpoints, jobs; compiled is not registered), with its controls, labels and help texts;
- every external value read or written, its direction (from the code, not the name) and its contract entry;
- library behavior the docs rely on, read in the source revision that matches the shipped binary, marked "(library)";
- code that looks unintended: a candidate behavior to confirm, with its cause.

## 3. Stop and show the outline

Outline of each document, diagram list, candidate behaviors to confirm, premises of the request the code contradicts, and the questions that change the docs, each with a recommended answer (at most four independent ones in this message; ask any that depends on another one at a time). Wait for the go.

## 4. Documents

Every document: numbered sections (stable links, findable by number); a header with commit, versions and links to the sibling docs; sections readable on their own; each fact in one document only, the others link to it.

- Knowledge base, with no code identifiers except external names and log messages: overview and context diagram; glossary; states and saved values; where the app appears and how it starts; what the user sees; one section per function (when usable, what happens, what is visible after, which external values change); automatic behaviors; external values (how to find each in the contract files, one worked example per mechanism); troubleshooting; behaviors to confirm (B1..Bn, each with the test that shows it).
- Test guide: setup (equipment, default state, inputs to send, how to reach each starting state); test index with the knowledge base sections and B items each test covers (at least one test per function, automatic behavior and observable B item); test cases as tables of step, action, expected screen or output, expected external value.
- Developer guide: quick start (layout, build and run commands marked "not run" when not run, logs, a reading path of 5 to 8 functions); architecture with an overview diagram; how a user action reaches the outside; state and invariants; key flows; components; interface table (code constant, external name, contract id, direction); persistence; recipes and pitfalls; unused code; causes of the behaviors to confirm; file index (file, sections that describe it).

## 5. Write

- In the knowledge base and test guide, write external values as name = value, never raw bytes.
- Trace each expected test value through the code in step order, including the state earlier steps leave.
- Compute worked examples with a command; choose inputs away from rounding edges.
- Write "(library)" or "not verified" where a claim rests on something you did not read.
- Diagrams: PlantUML in the docs' diagrams folder, kb_ or dev_ prefix, no style file, theme or colors, because PlantUML's defaults stay readable in light and dark viewers; render to SVG, look at each render, split any too wide to read.

## 6. Verify

Run each check as a one-off command, after seeing it catch an error planted in a scratch copy:

1. every external value in the code appears in the knowledge base and the developer guide, with one contract entry per direction that exists in the spec;
2. every relative link, image and anchor resolves, and a link text with a section number points to that section;
3. no placeholders, TODOs or forbidden characters;
4. no code identifiers in the knowledge base or test guide;
5. every diagram renders: exit code 0 and nothing on stderr.

Then the fact-check: one reviewer subagent per document, given the document, the code and the specs but not your notes, returning wrong or unsupported claims with file:line. Re-check each finding at the source before fixing it, then re-run checks 1 to 5.

## 7. Update

Run git diff --stat <recorded commit>..HEAD, find the affected sections through the developer guide's file index, re-map and rewrite only those, update the header, then run checks 1 to 5 on all docs and the fact-check on the changed sections. Without a recorded commit, do a full run that keeps the existing structure.

## 8. Report

Files changed, decisions taken, behaviors to confirm and contract anomalies found, what was verified and what was not. Offer one line for the project's AGENTS.md that points agents to the docs. Commit only when asked.
