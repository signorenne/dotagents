---
name: session-close
description: "Closes a working session in a repository: records the real state of the work in the project's handoff format from git and the commands actually run, settles pending decisions with the user, and leaves a handoff the next fresh session can resume from. Use when the user says the session is over, asks to close, wrap up or hand off work in a repository, or before clearing the context."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Session close

1. Collect facts with commands, not from memory: current branch, git status --short, git log --oneline from the merge base with main to HEAD, git diff --stat HEAD. Commands run in this session and their results come from the session itself; list only commands that actually ran.
2. Fill the project's handoff template when it has one (Goal, Files touched, Decisions, Open questions, Commands run, Commands still needed, Risks). Commands still needed must include every documented gate not run since the last code change.
3. Name the code-level facts the next session will depend on (files, symbols, signatures) and mark them "verify before use": they may change before the next session reads the handoff.
4. Decisions: list each decision made in this session that the decision log does not hold yet and that meets its recording bar. Ask the user to accept, reject or leave each as Proposed, then write them accordingly (Accepted only when the user confirmed, decided by the user).
5. Write the handoff to the project's working-notes location (for example .private/handoff/<YYYY-MM-DD>-<slug>.<ext> when .private/ is git-ignored; otherwise ask once), in the project's prose format.
6. Uncommitted work: list it and ask whether to commit it as the next logical step, leave it, or stash it. Never push.
7. Reply with the handoff path and the single next action, phrased for a fresh session (for example: start a fresh session, then run the implement skill on .private/specs/<slug> from step N).
