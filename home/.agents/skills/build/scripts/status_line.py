#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Claude Code status line: the branch, the plan's Status and Next, and the context used, so the
state of the work shows without asking for it.

  "statusLine": {"type": "command",
                 "command": "python3 \"$HOME/.agents/skills/build/scripts/status_line.py\"",
                 "refreshInterval": 10}

Reads the status line JSON on stdin (workspace.current_dir, else cwd; context_window.
used_percentage, which may be null) and prints one line, for example
"feat/widget | in progress | next: S2 add the widget's test | ctx 42%" ("detached" on a
detached HEAD). It makes one git call with a short timeout (two in a linked worktree), and
on any failure prints a short line and exits 0, since an empty output or a non-zero exit
leaves the status line blank.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import planfile  # beside this script

planfile.GIT_TIMEOUT = 1.0
NEXT_CHARS = 60


def status(payload: dict) -> str:
    workspace = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
    cwd = workspace.get("current_dir") or payload.get("cwd") or "."
    parts = []
    if Path(cwd).is_dir():
        state, _, plan = planfile.locate(cwd, full=False)
        if state:
            parts.append(state.get("branch") or "detached")
        if plan is not None:
            header = planfile.read(plan)["header"]
            if header.get("Status"):
                parts.append(header["Status"])
            if header.get("Next"):
                text = header["Next"]
                parts.append("next: " + (text if len(text) <= NEXT_CHARS else text[:NEXT_CHARS - 3] + "..."))
    window = payload.get("context_window") if isinstance(payload.get("context_window"), dict) else {}
    used = window.get("used_percentage")
    if isinstance(used, (int, float)) and not isinstance(used, bool):
        parts.append(f"ctx {round(used)}%")
    return " | ".join(parts) or "no repository"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        line = status(payload if isinstance(payload, dict) else {})
    except Exception:  # the status line must never go blank
        line = "status unavailable"
    print(line.replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
