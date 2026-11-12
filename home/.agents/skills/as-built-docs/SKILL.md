---
name: as-built-docs
description: "Writes as-built documentation of an existing repository or app from its code, as files in the repository, for people to read: a knowledge base of how it works for technical non-developers, a manual test guide and a developer guide, each opening with its own vocabulary and the big picture, with UML diagrams (class diagrams with their key members), annotated pictures of the screens and a reference appendix for agents, every statement traced to code and fact-checked, and synced instead of rewritten when the code changes. Use when the user asks to document a repository or app (knowledge base, test guide, developer guide, onboarding or architecture docs of existing code), or to update such docs after the code changed. Not for finding bugs or code smells (code-audit) or planning a new system (architecture-doc)."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# As-built docs

Goal: three documents that a person reads easily and can trust. They say how the software works at one commit, in plain words, the big picture first, every statement taken from code or a spec you read. A wrong statement is worse than a missing one, and a peculiarity the reader never meets is noise.

## Working rules

- Keep facts in a notes file (.private/as-built/notes.md when .private/ is git-ignored, otherwise a scratch folder), one line each: id, area tag, statement, file:line. Write from the notes: they survive compaction and spare rereading the code.
- Delegate code reading, one area per read-only subagent, returning facts in that line format (in Claude Code the general-purpose subagent told not to edit; elsewhere scout, told to return facts in that format instead of its brief). Run commands whose output you need yourself, saved to a file you search; gate-runner only for pass or fail checks with long logs.
- External value: a named value the software exchanges with another system (message or signal field, API parameter, configuration key, file field), defined in a contract (API spec, schema, message database) owned by whoever maintains that definition.
- Describe the software as built, without judging it: no bugs, suspicions, unused code or contract anomalies in the docs. Note each one in the notes file under "for the audit", with file:line, and hand the list over at the end.
- Write one document and one section at a time.

## 1. Inputs

Take them from the request, the repository and its existing docs; ask only what none of them settles.

- Code path, docs folder, file names, language, markup and conventions (match the existing docs).
- Documents: knowledge base, test guide, developer guide. Drop one that has no reader (a library has no manual test guide).
- Where the external contracts are defined (API specs, schemas, protocol databases): the names in the code are only half of each contract.
- The commit and versions described, each with its source.
- Existing docs that record a commit: go to section 9 and sync them; never write them again from scratch.

## 2. Map the code

Note, with file:line:

- features, states, what is saved and restored, startup, timers, limits, defaults;
- every surface actually registered (screens, commands, endpoints, jobs; compiled is not registered), with its controls, labels and help texts, and each screen's states;
- the UI structure: screens, views and components, and the view model or class behind each;
- every external value read or written, its direction (from the code, not the name) and its contract entry;
- the structure: layers or modules and their dependencies, the main classes of each with their key public members and relationships, and the main flows end to end;
- library behavior the docs rely on, read in the source revision that matches the shipped binary;
- the reference data for the appendix (persistence keys, identifiers, external values to code, configuration keys), each with the command that extracts it from the code, saved in the notes so an update can run it again.

## 3. Stop and show the outline

The outline of each document with the purpose of each section, the vocabulary terms of each, the diagram list, the pictures (screen and state, and whether the app can run and be driven here), premises of the request the code contradicts, and the questions that change the docs, each with a recommended answer (asked as the decide skill groups questions). Wait for the go.

## 4. How to write

- Header: one line with the commit, the versions and links to the sibling documents.
- Section 1, Vocabulary: the 10 to 15 terms this document's reader needs first, one sentence each, in the order they first appear. A term shared with a sibling document is worded the same in both. Define any other term where it first appears.
- Section 2, The big picture: what the software is for, then how it works in 3 to 6 numbered steps and one diagram, all within the first 300 words.
- Every other section opens with what it covers and why it matters, then the normal case and one example. Exceptions follow in a short Details list; a peculiarity the reader never meets stays out.
- One idea per sentence, split above about 25 words; one topic per paragraph, at most 5 sentences; active voice; one term per concept.
- Numbers only where they explain something or the reader types or reads them. Tables only for lookups (items with several attributes, if-then rules), each introduced by a sentence.
- Each fact has one home, and a sibling document links to it rather than repeating it, at most one cross-reference per paragraph. The vocabulary and the external values are the exceptions: the knowledge base explains external values, the developer guide's appendix maps them to code.
- Numbered, descriptive headings, so links stay stable.

Accuracy:

- In the knowledge base and test guide, write external values as name = value, never raw bytes.
- Trace each expected test value through the code in step order, including the state earlier steps leave.
- Compute worked examples with a command; choose inputs away from rounding edges.
- Write "not verified" where a claim rests on something you did not read; keep library sources in the notes and the appendix, not in the prose.

## 5. The documents

- Knowledge base, for technical non-developers, with no code identifiers except external names and log messages, about 2,500 to 3,500 words: vocabulary; the big picture with a context diagram; the core model (the mechanism the rest depends on) with its diagram; where the app appears; the screens, one picture each with numbered markers and a legend (element, what it shows, what you can do with it); one section per function (what it does, when it is available, what you see, which external values change, one example, and before and after pictures when it changes the screen); automatic behaviors (what is saved and restored, safety rules, language and units); reference lookups (external values with one computed contract example per mechanism, values per state); troubleshooting (symptom, cause, action).
- Test guide, for testers, about 400 to 600 words before the test cases: vocabulary; how testing works (a bench diagram and the few rules every test relies on); setup (equipment, named starting states with a picture of each, and how to reach each); an index of tests by function; test cases in knowledge base order, each with one sentence of purpose, its starting state and a table of step, action, expected screen, expected external value, with a cropped picture of the expected screen where its look is what the step tests; what to record when a step fails. Every function and automatic behavior has a test, and tests check the current behavior.
- Developer guide, for developers, about 3,000 to 4,000 words before the appendix: vocabulary of code concepts; architecture at a glance (the data flow in numbered steps, a component diagram by layer, the few design decisions with their reasons); code structure (a layer or package diagram and a short folder table); UI structure (a component diagram of screens, views and components with the view model or class behind each, and the annotated picture of each screen naming the component behind each element); one class diagram per layer or area, each with a paragraph on its responsibilities; behavior (the core state diagram and one sequence per main flow, each with the rules it keeps); persistence; recipes for common changes and the design constraints behind them; build, run and release. Appendix A, Reference, tables only, for maintainers and agents: external values to code (code constant, external name, contract id, direction), persistence keys, identifiers, configuration keys, and the file index (file, sections that describe it). The identifiers the prose leaves out live here.

## 6. Diagrams and pictures

PlantUML in the docs' diagrams folder with a kb_, tg_ or dev_ prefix, drawn and checked with the plantuml-diagrams skill; without plantuml, say so and mark the diagrams not rendered. Each diagram has a title (the question it answers), appears in one document only, and opens the section it explains. Class diagrams show each class's key members. The usual set: in the knowledge base the context, the core model and one per complex function; in the test guide the bench; in the developer guide the components by layer, the packages, the class diagrams, the core state machine, one sequence per main flow and persistence.

Pictures of the UI come from the real app, never from a drawing of how it might look:

- Run the app and drive it to each screen and state with the input it really gets: clicks, touches and keys, and the signals or messages it receives (through the project's simulator or test harness). Then grab the window or the framebuffer: through the project's screenshot or scenario tests when it has them, otherwise with the platform's tools (for example grim on Wayland, import from ImageMagick on X11, a framebuffer dump on a device).
- Make each picture repeatable, as section 1 of the precise-ui-changes skill says (fixed data and clock, settled animations, device pixels), and save its recipe in the notes (how to start the app, the input sequence, the grab command, the crop and markers), so an update renders it again.
- When the app cannot run or be driven here, list the screens and states you need and ask the user for the pictures; write those sections once they arrive.
- Pictures are PNG files in the docs' images folder with the kb_, tg_ or dev_ prefix, cropped to what the section explains.
- Mark each element the text explains with the bundled script: in Claude Code python3 ${CLAUDE_SKILL_DIR}/scripts/annotate.py, elsewhere python3 ~/.agents/skills/as-built-docs/scripts/annotate.py (it needs Pillow: ask before installing it). Place each marker at the edge of its element, not over text the reader needs; the legend under the picture uses the same numbers.

## 7. Verify

Run each check as a one-off command saved in the notes (the update runs them again), after seeing it catch an error planted in a scratch copy:

1. every external value in the code appears in the knowledge base and in the appendix, with one contract entry per direction that exists in the spec;
2. the appendix matches the code both ways: every entry exists at the described commit, and every key, identifier and mapping the extraction commands find is listed;
3. every relative link, image and anchor resolves, and a link text with a section number points to that section;
4. no placeholders, TODOs or characters the project forbids, and no code identifiers in the knowledge base or test guide except external names and log messages;
5. readability: the big picture within the first 300 words of each document; at most about 5 code identifiers per 100 words of prose outside the appendix; at most one cross-reference per paragraph; no sentence over 35 words; every section opens with prose; each document within its word budget;
6. every diagram renders (exit code 0 and nothing on stderr) and has a title, and every class in a class diagram shows members;
7. every picture exists, has its recipe in the notes or is marked as provided by the user, and has a legend with as many entries as it has markers.

Then the fact-check: one subagent per document that did not write it (in Claude Code the general-purpose subagent told not to edit; elsewhere the reviewer, told to review the document, not the branch diff), given the document, the code and the specs but not your notes. It returns wrong or unsupported claims with file:line, and the passages where a reader without your notes gets lost. Re-check each finding at the source before fixing it, then run checks 1 to 7 again.

## 8. Report

Files changed, decisions taken, what was verified and what was not, the pictures still missing (for the user to provide), and the list for the audit (suspicious behavior, unused code, contract anomalies, each with file:line), to be checked with the code-audit skill. Offer one line for the project's AGENTS.md that points agents to the developer guide and its appendix. Commit only when asked.

## 9. Update

Sync the docs to the code; never write them again from scratch.

1. Read the recorded commit from the headers and run git diff --stat <recorded commit>..HEAD.
2. Find the affected sections through the appendix's file index. Map only the changed areas again, run the appendix's extraction commands from the notes again, and render again the pictures of the screens that changed.
3. Rewrite only the affected sections, vocabulary entries, diagrams, pictures and appendix rows, and update the commit in the headers.
4. Run checks 1 to 7 on all the docs, and the fact-check on the changed sections.

Docs in an earlier layout of this skill are migrated once to this structure, keeping what is still true: show the new outline first (section 3), and move behaviors to confirm, unused code and anomalies to the list for the audit. For docs without a recorded commit, ask whether to migrate them or to keep their structure.
