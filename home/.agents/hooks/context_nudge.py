#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""PostToolUse hook (Claude Code, matcher Bash): after a step's commit, when the context
is large, tell the user in one line that this is a good point to clear the session.

A step boundary is a shell command that ran git commit. The context is the last main
request's input, cache-write and cache-read tokens, read from the tail of the session's
transcript (transcript_path in the hook input). The hint appears only on a task branch
whose plan file exists (the build skill's planfile.py finds it), because only then does
the plan hold the state a fresh session resumes from. Clearing costs nothing that the
plan does not hold, and a long context is re-read, and paid for, on every request.

Usage: python3 "$HOME/.agents/hooks/context_nudge.py" || true
Output: {"systemMessage": ...} on stdout, which Claude Code shows the user. Anything
unreadable, a missing transcript or planfile.py, a small context, or another command:
no output. Always exits 0.
"""

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # importing planfile leaves no cache in ~/.agents
SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "build" / "scripts"
try:
    sys.path.insert(0, str(SCRIPTS))
    import planfile
    planfile.GIT_TIMEOUT = 1.5  # about five calls stay under the 10 s hook timeout
except Exception:  # a missing or broken build skill: no hint
    planfile = None

THRESHOLD = 200_000
TAIL_BYTES = 4_000_000
COMMIT = re.compile(r"(^\s*|[;&|(]\s*)git(\s+-C\s+\S+)?(\s+-c\s+\S+)*\s+commit(?=\s|$|[;&|)])")


def context_tokens(transcript: Path):
    """The context of the last main request in the transcript, or None."""
    with transcript.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - TAIL_BYTES))
        lines = handle.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get("message") if isinstance(record, dict) else None
        usage = message.get("usage") if isinstance(message, dict) else None
        if record.get("type") == "assistant" and not record.get("isSidechain") and isinstance(usage, dict):
            return sum(usage.get(key) or 0 for key in
                       ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return None


def hint(payload: dict):
    command = (payload.get("tool_input") or {}).get("command")
    transcript, cwd = payload.get("transcript_path"), payload.get("cwd")
    if not (isinstance(command, str) and COMMIT.search(command) and isinstance(transcript, str)
            and isinstance(cwd, str) and cwd and planfile is not None):
        return None
    tokens = context_tokens(Path(transcript))
    if tokens is None or tokens < THRESHOLD:
        return None
    _, _, plan = planfile.locate(cwd)
    if plan is None:
        return None
    return (f"Context at {tokens // 1000}k tokens after a step's commit: a good point to clear the "
            f"session (/clear). The plan {plan.name} holds the state, and the session hook prints it back.")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        message = hint(payload) if isinstance(payload, dict) else None
        if message:
            print(json.dumps({"systemMessage": message}))
    except Exception:  # a hint is never worth a failed tool call
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
