#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Stop hook (Claude Code and Codex): record the branch's commits in the plan's log, so
no model turn is spent writing them.

On a task branch <type>/<slug> whose plan file .private/plans/<slug>.<ext> exists (found
by the build skill's planfile.py: the nearest .private, or in a linked worktree the main
checkout's), it appends to <slug>.log one "commit" line for each commit of the branch
the log does not name yet: the commits of HEAD that no other local branch and no
remote-tracking branch holds (the 50 newest), oldest first. A commit counts as named
when a commit line holds a prefix of its hash of at least 7 characters.

Usage: python3 "$HOME/.agents/hooks/step_log.py" || true
It prints nothing and always exits 0: it never keeps the agent going. Unreadable input,
a missing planfile.py, a slow or failing git and any other error only skip the writing.
"""

import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # importing planfile leaves no cache in ~/.agents
SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "build" / "scripts"
try:
    sys.path.insert(0, str(SCRIPTS))
    import planfile
    planfile.GIT_TIMEOUT = 1.5  # about five calls stay under the 10 s hook timeout
except Exception:  # a missing or broken build skill skips the writing
    planfile = None

MAX_COMMITS = 50


def named(full: str, recorded: set) -> bool:
    return any(full[:n] in recorded for n in range(7, len(full) + 1))


def record(cwd: str) -> list:
    """Append the missing commit lines; return them."""
    state, _, plan = planfile.locate(cwd, full=False)
    if plan is None:
        return []
    recorded = {row["commit"].lower() for row in planfile.log_lines(plan) if row["kind"] == "commit"}
    branch = state["branch"]
    listed, ok = planfile.git(
        ["log", f"--max-count={MAX_COMMITS}", "--reverse", "--format=%H%x09%ct%x09%s", "HEAD", "--not",
         f"--exclude={branch}", "--branches", "--remotes", "--"], cwd)
    if not ok:
        return []
    written = []
    for line in listed.splitlines():
        full, _, rest = line.partition("\t")
        when, _, subject = rest.partition("\t")
        if not full or named(full.lower(), recorded):
            continue
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(int(when)))
        written.append(planfile.append_log(plan, time=stamp, step="-", kind="commit", commit=full[:12],
                                           result="-", tests="-", command=subject))
    return written


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        cwd = payload.get("cwd") if isinstance(payload, dict) else None
        if planfile is not None and isinstance(cwd, str) and cwd:
            record(cwd)
    except Exception:  # never keep the agent going because of a broken hook
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
