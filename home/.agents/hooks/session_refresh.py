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
TIMED_OUT = "did not finish in time"
FAILED = "failed"


def git(*args: str, cwd: str, deadline: float) -> tuple[str, str]:
    """Return (output, problem): problem is "" on success, TIMED_OUT when git did not
    answer in time or was skipped for lack of time, FAILED when it failed."""
    left = deadline - time.monotonic()
    if left < MIN_CALL_SECONDS:
        return "", TIMED_OUT
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                                timeout=min(CALL_TIMEOUT_SECONDS, left), check=False)
    except subprocess.TimeoutExpired:
        return "", TIMED_OUT
    except OSError:
        return "", FAILED
    if result.returncode != 0:
        return "", FAILED
    # Only trailing newlines: a leading space is the index column of git status --short.
    return result.stdout.rstrip("\n"), ""


def text_field(payload: dict, key: str, default: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) and value else default


def main() -> int:
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        payload = json.load(sys.stdin)
    except (ValueError, RecursionError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    cwd = text_field(payload, "cwd", ".")
    source = text_field(payload, "source", "resume or compaction")

    lines = [
        f"Session restarted from {source}. Everything you remember about the code is a "
        "summary and may be stale: functions may have been renamed or removed. Before "
        "editing or calling code, re-read the files involved and confirm each symbol "
        "with a search; state in one line what you will change before each edit.",
    ]
    # A list that is missing for lack of time or a git error is named, so it is never
    # read as a clean tree. Outside a repository git branch fails and nothing is shown.
    branch, problem = git("branch", "--show-current", cwd=cwd, deadline=deadline)
    if problem == TIMED_OUT:
        lines.append("Git state not shown: git did not answer in time.")
    elif not problem:
        if branch:
            lines.append(f"Current branch: {branch}")
        else:
            head, problem = git("rev-parse", "--short", "HEAD", cwd=cwd, deadline=deadline)
            lines.append(f"Detached HEAD at {head}" if head
                         else f"Detached HEAD; its commit not shown: git rev-parse {problem}.")
        # --no-optional-locks: a status stopped by the timeout leaves no .git/index.lock.
        # --no-branch: with status.branch set, the "## branch" line is not a change.
        status, problem = git("--no-optional-locks", "status", "--short", "--no-branch",
                              cwd=cwd, deadline=deadline)
        if problem:
            lines.append(f"Uncommitted changes not shown: git status {problem}.")
        elif status:
            changes = status.splitlines()
            shown = changes[:MAX_STATUS_LINES]
            more = len(changes) - len(shown)
            lines.append("Uncommitted changes:\n" + "\n".join(shown)
                         + (f"\n... and {more} more" if more > 0 else ""))
        # git log fails in a repository without commits; that needs no notice.
        recent, problem = git("log", "--oneline", "-5", cwd=cwd, deadline=deadline)
        if problem == TIMED_OUT:
            lines.append(f"Last commits not shown: git log {problem}.")
        elif recent:
            lines.append("Last commits:\n" + recent)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
