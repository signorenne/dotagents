---
name: spec
description: "Turns a feature idea into a self-contained implementation spec through scouting and a maieutic interview, without writing any code. Use when the user asks for a spec, an implementation plan or a design doc for one increment of an existing repository, or before a new module, a public component with open design choices, or any change that spans modules."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Spec

Goal: a spec that a fresh session, with no access to this conversation, can implement correctly. Write no source code in this session; the only files you write are the spec and, with the user's approval, decision entries.

1. Map the area: delegate to scout with the feature description and ask for its standard brief. Re-read a file yourself only when a detail decides the design.
2. Follow the project's spec workflow when it has one (for example a "Spec workflow" section in its agent workflows doc). It defines the location and the sections. If the project has none, write to .private/specs/<slug>.<ext> when .private/ is git-ignored (otherwise ask once where specs go), in the project's prose format, with these sections: objective, non-goals, affected areas, public surface, reuse, behavior and edge cases, deliverables (tests, examples, docs), decisions, acceptance criteria, verification commands, open questions.
3. Settle each open design choice with the decide skill: one decision at a time, recommended option first, stop when remaining unknowns would not change the design. Independent low-stakes choices can be grouped (at most four, each with a default).
4. Write the spec. Name exact files, types, functions, error behavior and commands, all checked against the current code. Write each acceptance criterion as an observable behavior that a test or a command can fail. No "as discussed", no references to this conversation.
5. Verify the spec before handing it over. Delegate it to a subagent that did not write it (in Claude Code the general-purpose subagent, told it must not edit anything; elsewhere the reviewer subagent with the spec path in place of a diff, checking the external facts yourself because it has no web access; without subagents, do it yourself following ~/.agents/agents/reviewer.md after re-reading each source). Ask it to check every file, symbol, signature, command and external fact the spec names against the current code and the cited documentation, to report each claim that is wrong or unverifiable with its evidence, and to name each requirement that no test or command could fail or that conflicts with another. Fix the spec. Before keeping any change to a requirement or decision the user already settled, show it to the user.
6. Decisions: list by id the Accepted entries the spec relies on and the entries decide recorded in step 3. For a choice settled outside decide that meets the decision log's recording bar, draft an entry and ask whether to add it; write it as Accepted only after explicit confirmation.
7. Stop. Reply with the spec path, the open questions, and the next step: start a fresh session (in Claude Code: /clear) and run the implement skill on the spec path.
