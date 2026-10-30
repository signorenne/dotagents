#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""SessionStart hook (Claude Code, matcher "compact|resume"): after a compaction or a
resume, remind the agent that its picture of the code is a summary and print the real
repository state, so stale function names are caught before they cause edits.

Usage: python3 "$HOME/.agents/hooks/session_refresh.py"
Plain stdout on exit 0 is added to the agent's context. Never fails the session.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

MAX_STATUS_LINES = 15
# Total budget for all git calls, under the 10 s hook timeout in
# adapters/claude/settings.json: Claude Code drops all output of a hook that times out.
DEADLINE_SECONDS = 8
CALL_TIMEOUT_SECONDS = 5
MIN_CALL_SECONDS = 0.5


def git(*args: str, cwd: str, deadline: float) -> str | None:
    """Output of git, "" when it fails, None when it timed out or was skipped for time."""
    left = deadline - time.monotonic()
    if left < MIN_CALL_SECONDS:
        return None
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                                timeout=min(CALL_TIMEOUT_SECONDS, left), check=False)
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return ""
    # Only trailing newlines: a leading space is the index column of git status --short.
    return result.stdout.rstrip("\n") if result.returncode == 0 else ""


def main() -> int:
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = payload.get("cwd") or "."
    source = payload.get("source") or "resume or compaction"

    lines = [
        f"Session restarted from {source}. Everything you remember about the code is a "
        "summary and may be stale: functions may have been renamed or removed. Before "
        "editing or calling code, re-read the files involved and confirm each symbol "
        "with a search; state in one line what you will change before each edit.",
    ]
    # A list that is missing for lack of time is named, so it is never read as a clean tree.
    branch = git("branch", "--show-current", cwd=cwd, deadline=deadline)
    if branch is None:
        lines.append("Git state not shown: git did not answer in time.")
    elif branch:
        lines.append(f"Current branch: {branch}")
        # --no-optional-locks: a status stopped by the timeout leaves no .git/index.lock.
        # --no-branch: with status.branch set, the "## branch" line is not a change.
        status = git("--no-optional-locks", "status", "--short", "--no-branch", cwd=cwd,
                     deadline=deadline)
        if status is None:
            lines.append("Uncommitted changes not shown: git status did not finish in time.")
        elif status:
            changes = status.splitlines()
            shown = changes[:MAX_STATUS_LINES]
            more = len(changes) - len(shown)
            lines.append("Uncommitted changes:\n" + "\n".join(shown)
                         + (f"\n... and {more} more" if more > 0 else ""))
        recent = git("log", "--oneline", "-5", cwd=cwd, deadline=deadline)
        if recent is None:
            lines.append("Last commits not shown: git log did not finish in time.")
        elif recent:
            lines.append("Last commits:\n" + recent)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
