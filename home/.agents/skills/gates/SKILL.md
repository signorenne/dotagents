---
name: gates
description: "Runs the project's documented build, test, sanitizer, lint, format and docs gates through the gate-runner subagent and reports only verdicts and the first errors, keeping long logs out of the conversation. Use when the user asks to run the gates, the tests, CI locally, or to check that a change builds."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Gates

Scope from the user's words: "full" (default) means the project's pre-PR gates; "narrow <module or test filter>" means one module's tests or one test case.

1. Find the commands in the project's docs: the Validation commands section of AGENTS.md, the contributing guide, or a CI-mirroring script those docs name. Never invent a command or a flag.
2. List the touched files (git diff --name-only against the merge base with main, plus uncommitted changes) so docs or per-module targets can be chosen.
3. Delegate to gate-runner with: the exact commands, the scope, and the touched files.
4. Relay its table (gate, command, PASS, FAIL or SKIP with reason) and, for each failure, the first errors with path:line and the log path. Add nothing else.

If no gate-runner subagent is available, follow ~/.agents/agents/gate-runner.md yourself and keep only the extracted errors in the conversation.
