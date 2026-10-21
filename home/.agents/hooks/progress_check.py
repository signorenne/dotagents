#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Stop hook (Claude Code and Codex): before the agent ends its turn on a task branch,
check that the task's progress log records the branch's commits.

On a branch named <type>/<slug> whose progress log .private/progress/<slug>.* exists
(in the working folder or a parent, or in a linked worktree in the main checkout:
session_refresh.py's finder), it blocks the stop once when a commit of the branch is
newer than the log's last change or its hash is missing from the log. The commits of
the branch are those of HEAD that no other local branch and no remote-tracking branch
holds (the 50 newest). A hash counts as recorded when the log holds a prefix of it of
at least 7 characters.

Usage: python3 "$HOME/.agents/hooks/progress_check.py" || true
Blocking: {"decision": "block", "reason": ...} on stdout with exit 0, which both tools
read as "continue with this reason". It lets the stop through, printing nothing, when
stop_hook_active is anything but false (true: the agent already continued because of
a stop hook; missing: Cursor, which runs Claude Code's Stop hooks with its own input
and no cap on follow-ups), outside such branches, and on any error, unreadable input or
lack of time. The "|| true" of the hook command covers what the script cannot: python3
exits 2 when the script is missing, and exit 2 from a Stop hook keeps the agent going.
"""

import json
import re
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # importing session_refresh leaves no cache in ~/.agents/hooks
try:
    import session_refresh
except Exception:  # a missing or broken copy lets every stop through
    session_refresh = None

TASK_BRANCH = re.compile(r"^[a-z]+/([A-Za-z0-9._-]+)$")
HASH = re.compile(r"[0-9a-f]{7,40}")
# Under the 10 s hook timeout: Claude Code drops all output of a hook that times out.
DEADLINE_SECONDS = 8
MAX_COMMITS = 50
MAX_LOG_BYTES = 4_000_000
MAX_LISTED = 10


def progress_log(private: Path, slug: str):
    """The newest file .private/progress/<slug>.<ext>, or None."""
    logs = [p for p in (private / "progress").glob(f"{slug}.*") if p.is_file()]
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def unrecorded(cwd: str, deadline: float):
    """(branch, log path, short hashes of the commits the log misses), or None when
    nothing is due or anything cannot be read."""
    branch, problem = session_refresh.git("branch", "--show-current", cwd=cwd, deadline=deadline)
    match = TASK_BRANCH.match(branch) if not problem else None
    if not match:
        return None
    private = session_refresh.private_folder(cwd, deadline)
    log = progress_log(private, match.group(1)) if private else None
    if log is None:
        return None
    changed = log.stat().st_mtime
    with log.open("rb") as handle:
        text = handle.read(MAX_LOG_BYTES).decode("utf-8", errors="replace").lower()
    recorded = set(HASH.findall(text))
    # Commits of HEAD that no other local branch and no remote-tracking branch holds.
    listed, problem = session_refresh.git(
        "log", f"--max-count={MAX_COMMITS}", "--format=%H %ct", "HEAD", "--not",
        f"--exclude={branch}", "--branches", "--remotes", "--", cwd=cwd, deadline=deadline)
    if problem:
        return None
    missing = []
    for line in listed.splitlines():
        full, _, when = line.partition(" ")
        if int(when) > changed or not any(full[:n] in recorded for n in range(7, len(full) + 1)):
            missing.append(full[:7])
    return (branch, log, missing) if missing else None


def reason(branch: str, log: Path, missing: list) -> str:
    shown = ", ".join(missing[:MAX_LISTED]) + (f" and {len(missing) - MAX_LISTED} more"
                                              if len(missing) > MAX_LISTED else "")
    return "\n".join([
        f"The progress log {log.as_posix()} is behind branch {branch}: it misses commit(s) "
        f"{shown}, made after its last change or not named in it.",
        "Before ending the turn, record in it each step those commits made, with its commit "
        "hash and the check you ran and its result; if a rebase only changed their hashes, "
        "replacing each old hash with its new one is enough.",
        "Then end the turn.",
    ])


def main() -> int:
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("stop_hook_active") is not False:
            return 0
        cwd = payload.get("cwd")
        if session_refresh is None or not isinstance(cwd, str) or not cwd:
            return 0
        found = unrecorded(cwd, deadline)
        if found:
            print(json.dumps({"decision": "block", "reason": reason(*found)}))
    except Exception:  # never keep the agent going because of a broken hook
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
