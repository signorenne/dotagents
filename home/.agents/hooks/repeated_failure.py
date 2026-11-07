#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""PostToolUseFailure hook (Claude Code, matcher Bash): notice when the same shell
command fails the same way again and again in one session, and remind the agent of the
rule for it: after two failed fixes, stop, restate the assumptions and the evidence,
and change approach.

Each failure of a Bash call is counted under a hash of its command and its whole error:
the first line as it is (for Bash, "Exit code N"), the rest with every word that holds
a digit masked, since timings, counts, dates, object addresses (0x7f3a...), Java hashes
(@6d06d69c) and temporary names (tmpab3x9k2q) change between runs of one failure, while
a test runner's fixed header does not tell two failures apart. The counts live in one
small file per session in the system temp folder, dotagents-failures-<session>.json,
which keeps the 200 most recent keys. On the third identical failure, and each one after
it, the hook returns hookSpecificOutput.additionalContext, which Claude Code puts next
to the error.

Usage: python3 "$HOME/.agents/hooks/repeated_failure.py" || true
Never blocks: it always exits 0. Unreadable input, an interrupt, another tool, a
missing session id or an unwritable temp folder only skip the count, and a count file
that is not its own starts the count again.
"""

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

THRESHOLD = 3
# A word that holds a digit; 0x addresses are such words.
VARYING = re.compile(r"\w*\d\w*")
MAX_KEYS = 200
MAX_STATE_BYTES = 64_000
MAX_SHOWN = 120
SAFE_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def state_file(session: str) -> Path:
    """The count file of a session; an id that is not a plain name is hashed, so the file
    always stays in the temp folder."""
    name = session if SAFE_SESSION.match(session) else hashlib.sha256(
        session.encode("utf-8", "surrogatepass")).hexdigest()[:32]
    return Path(tempfile.gettempdir()) / f"dotagents-failures-{name}.json"


def load(path: Path) -> dict:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_STATE_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items()
            if isinstance(value, int) and not isinstance(value, bool) and value > 0}


def save(path: Path, counts: dict) -> None:
    """Replace the file whole, so a parallel call never reads half of it."""
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(counts, out)
        os.replace(temporary, str(path))
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def count(payload: dict):
    """(times this failure happened in the session, the command), or None when the
    payload is not a counted Bash failure."""
    command = payload.get("tool_input", {}).get("command") if isinstance(payload.get("tool_input"), dict) else None
    session, error = payload.get("session_id"), payload.get("error")
    if (payload.get("tool_name") != "Bash" or payload.get("is_interrupt") is True
            or not isinstance(session, str) or not session or not isinstance(error, str)
            or not isinstance(command, str) or not command.strip()):
        return None
    first, _, rest = error.partition("\n")
    shape = f"{command.strip()}\0{first}\0{VARYING.sub('#', rest)}"
    key = hashlib.sha256(shape.encode("utf-8", "surrogatepass")).hexdigest()[:16]
    path = state_file(session)
    counts = load(path)
    times = counts.pop(key, 0) + 1
    counts[key] = times  # the most recent last
    while len(counts) > MAX_KEYS:
        counts.pop(next(iter(counts)))
    save(path, counts)
    return times, command.strip()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        found = count(payload) if isinstance(payload, dict) else None
        if found and found[0] >= THRESHOLD:
            times, command = found
            shown = command.splitlines()[0][:MAX_SHOWN]
            shown += " ..." if shown != command else ""
            context = (f"This command failed the same way {times} times in this session: {shown}. "
                       "After two failed fixes, stop: restate your assumptions and the evidence, then "
                       "change approach (the systematic-debugging skill). If the new approach fails too, "
                       "stop and report to the user.")
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUseFailure",
                                                     "additionalContext": context}}))
    except Exception:  # never in the way: a failure only skips the reminder
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
