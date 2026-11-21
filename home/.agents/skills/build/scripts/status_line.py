#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Claude Code status line: the branch, the plan's Status and Next, the context used, the
rate limits and the model, so the state of the work shows without asking for it.

  "statusLine": {"type": "command",
                 "command": "python3 \"$HOME/.agents/skills/build/scripts/status_line.py\"",
                 "refreshInterval": 10}

Reads the status line JSON on stdin and prints one line, for example
"feat/widget | in progress | next: S2 add the widget's test | ctx 42% | 5h 37% (2h30m) |
7d 12% (4d3h) | Fable 5.2 high" ("detached" on a detached HEAD). Its parts, each left out
when the input lacks it or holds another type:

- the branch, Status and Next of the plan found from workspace.current_dir, else cwd;
- "ctx N%" from context_window.used_percentage;
- "5h N% (T)" and "7d N% (T)" from rate_limits.five_hour and seven_day: used_percentage,
  and T, the time to resets_at (epoch seconds) in whole minutes rounded down, as its two
  largest units (4d3h, 2h05m, 45m), left out once the reset is not after now;
- model.display_name, else model.id, then effort.level.

It makes one git call with a short timeout (two in a linked worktree), and on any failure
prints a short line and exits 0, since an empty output or a non-zero exit leaves the status
line blank.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import planfile  # beside this script

GIT_TIMEOUT = 1.0  # the line is redrawn every few seconds: a slow git call must not hold it
NEXT_CHARS = 60
LIMITS = (("five_hour", "5h"), ("seven_day", "7d"))  # the windows of rate_limits and their labels


def number(value) -> bool:
    """A finite int or float; a bool is not one."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def field(holder: dict, name: str) -> dict:
    """An object field, or an empty object when it is missing or of another type."""
    value = holder.get(name)
    return value if isinstance(value, dict) else {}


def text(value) -> str:
    """A string field, or the empty string when it is missing or of another type."""
    return value if isinstance(value, str) else ""


def time_left(seconds: float) -> str:
    """A time span in whole minutes, rounded down, as its two largest units."""
    minutes = int(seconds // 60)
    if minutes >= 1440:
        return f"{minutes // 1440}d{minutes % 1440 // 60}h"
    if minutes >= 60:
        return f"{minutes // 60}h{minutes % 60:02d}m"
    return f"{minutes}m"


def limit(label: str, window: dict, now: float) -> str:
    """A rate limit window as its use and the time to its reset: "5h 37% (2h30m)"."""
    used, reset = window.get("used_percentage"), window.get("resets_at")
    if not number(used):
        return ""
    left = f" ({time_left(reset - now)})" if number(reset) and reset > now else ""
    return f"{label} {round(used)}%{left}"


def status(payload: dict, now: float) -> str:
    """The line for one status line input; now is the clock, in epoch seconds."""
    cwd = field(payload, "workspace").get("current_dir") or payload.get("cwd") or "."
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
                next_step = header["Next"]
                parts.append("next: " + (next_step if len(next_step) <= NEXT_CHARS
                                         else next_step[:NEXT_CHARS - 3] + "..."))
    used = field(payload, "context_window").get("used_percentage")
    if number(used):
        parts.append(f"ctx {round(used)}%")
    limits = field(payload, "rate_limits")
    parts += [limit(label, field(limits, key), now) for key, label in LIMITS]
    model = field(payload, "model")
    name = text(model.get("display_name")) or text(model.get("id"))
    parts.append(" ".join(part for part in (name, text(field(payload, "effort").get("level"))) if part))
    return " | ".join(part for part in parts if part) or "no repository"


def main() -> int:
    planfile.GIT_TIMEOUT = GIT_TIMEOUT
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        line = status(payload if isinstance(payload, dict) else {}, time.time())
    except Exception:  # the status line must never go blank
        line = "status unavailable"
    print(line.replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
