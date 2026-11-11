#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""PreCompact hook (Claude Code): tell the compaction summary what resuming the work
needs. When a PreCompact hook exits 0, Claude Code uses its stdout as instructions for
the summary, cut at 10,000 characters. The brief asks the summary to keep the task and
its slug, the branch, the plan file's path (it holds the state: status, next step,
steps, rulings), the workflow skill and its running section or step, the current plan
step, the rulings still pending and the user's choices of this session, the user's
constraints that no file records (word for word) and what is blocked on what, the files
changed, and the commands still needed with their last results. It fills in what it can
read itself: the branch, the uncommitted changes, the plan file of a task branch (the
build skill's planfile.py) or else the newest files of .private/plans/ and
.private/handoff/ (session_refresh.py's finder).

Usage: python3 "$HOME/.agents/hooks/compact_brief.py" || true
Always exits 0: exit 2 blocks the compaction, and when the compaction recovers from a
full context the request then fails. Unreadable or missing input, a slow or failing
git and a missing session_refresh.py only shorten the brief; a character the output
encoding lacks is replaced. The "|| true" of the hook command
covers what the script cannot: python3 exits 2 when the script file is missing.
"""

import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # importing session_refresh leaves no cache in ~/.agents/hooks
try:
    import session_refresh
except Exception:  # a missing or broken copy only drops the facts read from disk
    session_refresh = None
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "build" / "scripts"))
    import planfile
    planfile.GIT_TIMEOUT = 1.0  # five calls leave time for the git state under the 10 s timeout
except Exception:  # without the build skill the brief names the newest notes instead
    planfile = None

# Claude Code cuts PreCompact stdout at 10,000 characters; stay well under it.
MAX_CHARACTERS = 9000
MAX_STATUS_LINES = 15
# Under the 10 s hook timeout in adapters/claude/settings.json: Claude Code drops all
# output of a hook that times out.
DEADLINE_SECONDS = 8
NOTES_SECONDS = 1


def read_payload() -> dict:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # not JSON, nested too deep, or no stdin at all
        return {}
    return payload if isinstance(payload, dict) else {}


def facts(cwd: str) -> tuple:
    """(branch, uncommitted changes, task notes) as text, each empty when unknown."""
    if session_refresh is None:
        return "", "", ""
    deadline = time.monotonic() + DEADLINE_SECONDS
    plan = None
    if planfile is not None:
        try:
            plan = planfile.locate(cwd, full=False)[2]
        except Exception:  # an unreadable plan only drops its path
            plan = None
    notes = (f"{plan} (the plan file of this branch)" if plan else
             "\n".join(session_refresh.task_notes(cwd, min(deadline, time.monotonic() + NOTES_SECONDS))))
    notes = notes.splitlines()
    branch, problem = session_refresh.git("branch", "--show-current", cwd=cwd, deadline=deadline)
    if problem:
        return "", "", "\n".join(notes)
    if not branch:
        head, _ = session_refresh.git("rev-parse", "--short", "HEAD", cwd=cwd, deadline=deadline)
        branch = f"detached HEAD at {head}" if head else ""
    status, problem = session_refresh.git("--no-optional-locks", "status", "--short", "--no-branch",
                                          cwd=cwd, deadline=deadline)
    changes = []
    if not problem and status:
        changes = status.splitlines()
        more = len(changes) - MAX_STATUS_LINES
        changes = changes[:MAX_STATUS_LINES] + ([f"... and {more} more"] if more > 0 else [])
    return branch, "\n".join(changes), "\n".join(notes)


def indented(text: str) -> str:
    return "\n".join("  " + line for line in text.splitlines())


def brief(branch: str, changes: str, notes: str) -> str:
    lines = [
        "Brief for this summary: the work goes on after it, so keep what resuming needs, "
        "without asking the user again:",
        "- The task: what the user asked, its slug, and the check that says it is done.",
        f"- The branch: {branch}." if branch else "- The branch the work is on.",
        "- The plan file's path, verbatim: it holds the state (status, next step, steps, rulings)"
        + (f". Task notes:\n{indented(notes)}" if notes else "."),
        "- The workflow skill in use (such as build or design) and the section or step of it "
        "that was running, so it is invoked again there.",
        "- The current plan step: the step in progress, the steps done and the steps left.",
        "- Each ruling still pending and each choice the user made in this session, with why.",
        "- Each constraint the user stated in this session that no file records, word for word, "
        "and what is blocked and on what.",
        "- The files changed, each with what changed"
        + (f". Uncommitted now:\n{indented(changes)}" if changes else "."),
        "- The commands still needed (gates, tests, checks), and the last result of each "
        "command run: the exact command and its outcome or first error.",
    ]
    return "\n".join(lines)


def main() -> int:
    cwd = read_payload().get("cwd")
    try:
        found = facts(cwd if isinstance(cwd, str) and cwd else ".")
    except Exception:  # never block a compaction: give the brief without the facts
        found = ("", "", "")
    try:
        sys.stdout.reconfigure(errors="replace")  # a branch name the output encoding lacks
        print(brief(*found)[:MAX_CHARACTERS])
    except Exception:  # no stdout to write to: the compaction goes on without the brief
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
