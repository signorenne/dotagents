#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""SessionStart hook (Claude Code, matcher "compact|resume"): after a compaction or a
resume, remind the agent that its picture of the code is a summary and print the real
repository state, so stale function names are caught before they cause edits.

Usage: python3 "$HOME/.agents/hooks/session_refresh.py"
Plain stdout on exit 0 is added to the agent's context. Never fails the session.
"""

import json
import subprocess
import sys

MAX_STATUS_LINES = 15


def git(*args: str, cwd: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                                text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def main() -> int:
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
    branch = git("branch", "--show-current", cwd=cwd)
    if branch:
        lines.append(f"Current branch: {branch}")
        status = git("status", "--short", cwd=cwd).splitlines()
        if status:
            shown = status[:MAX_STATUS_LINES]
            more = len(status) - len(shown)
            lines.append("Uncommitted changes:\n" + "\n".join(shown)
                         + (f"\n... and {more} more" if more > 0 else ""))
        recent = git("log", "--oneline", "-5", cwd=cwd)
        if recent:
            lines.append("Last commits:\n" + recent)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
