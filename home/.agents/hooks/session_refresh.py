#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""SessionStart hook (Claude Code and Codex, matcher "startup|resume|clear|compact").

On a task branch whose plan file exists, it prints the plan excerpt of the build skill's
plan_state.py --excerpt (status, next step, step in progress, open rulings), marked as a
map to check against git. On a new session or after a clear that is all it prints, and
nothing at all without a plan file. After a compaction or a resume it first reminds the
agent that its picture of the code is a summary and prints the real repository state
(branch, changes, last commits and the other worktrees), so stale function names are
caught before they cause edits; after a compaction it also asks the agent to invoke its
workflow skill again. Without a plan excerpt it lists instead the three most recent plan
files of .private/plans/ and files of .private/handoff/ (found in the working folder or
a parent, up to the repository root, or in a linked worktree in the main checkout), with
absolute paths.

Usage: python3 "$HOME/.agents/hooks/session_refresh.py" [--tool claude|codex|gemini|copilot|cursor]
Claude Code and Codex add plain stdout on exit 0 to the agent's context. Gemini CLI,
Copilot CLI and Cursor read JSON only (their sessionStart docs): {"hookSpecificOutput":
{"additionalContext": ...}}, {"additionalContext": ...} and {"additional_context": ...},
and {} when there is nothing to add. Copilot CLI's "new" source counts as a start, and
Cursor, which sends no source and no cwd, as a start in its first workspace root.
Never fails the session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

MAX_STATUS_LINES = 15
MAX_WORKTREES = 10
# Total budget for the notes listing and all git calls, under the 10 s hook timeout in
# adapters/claude/settings.json: Claude Code drops all output of a hook that times out.
DEADLINE_SECONDS = 8
CALL_TIMEOUT_SECONDS = 5
MIN_CALL_SECONDS = 0.5
TIMED_OUT = "did not finish in time"
FAILED = "failed"
NOTE_FOLDERS = ("plans", "handoff")
PLAN_SUFFIXES = (".org", ".md")
# The plan excerpt: the build skill's script, beside this folder once installed.
PLAN_STATE = Path(__file__).resolve().parent.parent / "skills" / "build" / "scripts" / "plan_state.py"
EXCERPT_SECONDS = 3
EXCERPT_CHARACTERS = 4000  # under Codex's cap of about 2,500 tokens per hook message
NOTES_PER_FOLDER = 3
# The notes listing runs first, so it gets a small share of the budget and a cap on the
# files it looks at; git gets the rest.
NOTES_SECONDS = 1
MAX_SCANNED_FILES = 2000
REREAD = "Re-read the task's plan file before the next step."
# After a compaction Claude Code re-attaches only the start (5,000 tokens) of each skill
# invoked before it, and may drop older ones; Codex documents nothing on it, so the line
# gives no tool's reason.
SKILL_AGAIN = "Invoke your workflow skill again before the next step."


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
    except (OSError, ValueError):  # ValueError: a folder name the system rejects, such as one with NUL
        return "", FAILED
    if result.returncode != 0:
        return "", FAILED
    # Only trailing newlines: a leading space is the index column of git status --short.
    return result.stdout.rstrip("\n"), ""


def text_field(payload: dict, key: str, default: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) and value else default


def private_folder(cwd: str, deadline: float) -> Path | None:
    """The .private folder in cwd or its nearest parent, not above the repository root.
    A linked worktree keeps its notes in the main checkout's: the folder that holds the
    common git folder (git rev-parse --git-common-dir)."""
    start = Path(cwd).absolute()
    for directory in (start, *start.parents):
        if (directory / ".private").is_dir():
            return directory / ".private"
        dot_git = directory / ".git"
        if dot_git.is_file():  # a linked worktree (or a submodule, whose notes stay unfound)
            common, problem = git("rev-parse", "--path-format=absolute", "--git-common-dir",
                                  cwd=str(directory), deadline=deadline)
            main = Path(common).parent / ".private" if common and not problem else None
            return main if main is not None and main.is_dir() else None
        if dot_git.exists():
            return None
    return None


def other_worktrees(porcelain: str, cwd: str) -> list[str]:
    """"path (branch)" lines for the worktrees in git worktree list --porcelain output,
    except the one that holds cwd, a bare repository and folders that no longer exist."""
    entries, entry = [], {}
    for line in porcelain.splitlines() + [""]:
        if line:
            key, _, value = line.partition(" ")
            entry[key] = value
            continue
        if entry.get("worktree"):
            entries.append(entry)
        entry = {}
    try:
        here = Path(cwd).resolve()
        paths = [Path(e["worktree"]).resolve() for e in entries]
        holders = [p for p in paths if p == here or p in here.parents]
        current = max(holders, key=lambda p: len(p.parts)) if holders else None
        lines = []
        for path, e in zip(paths, entries):
            if path == current or "bare" in e or "prunable" in e or not path.is_dir():
                continue
            branch = e.get("branch", "").replace("refs/heads/", "", 1)
            lines.append(f"{path.as_posix()} ({branch or 'detached at ' + e.get('HEAD', '')[:7]})")
        return lines
    except (OSError, ValueError, RuntimeError):
        return []


def task_notes(cwd: str, deadline: float) -> list[str]:
    """The most recent files of each note folder, newest first, as "path (modified)" lines
    with absolute paths, which hold from a subfolder or a worktree too. Errors and
    slowness only shorten the list."""
    try:
        private = private_folder(cwd, deadline)
        if private is None:
            return []
        lines, scanned = [], 0
        for name in NOTE_FOLDERS:
            found = []
            for folder, folders, files in os.walk(private / name):
                if scanned >= MAX_SCANNED_FILES or time.monotonic() > deadline:
                    break
                if name == "plans":  # the plans themselves, not their logs and run outputs
                    folders[:] = []
                    files = [f for f in files if f.endswith(PLAN_SUFFIXES)]
                for file in files[:MAX_SCANNED_FILES - scanned]:
                    scanned += 1
                    path = Path(folder) / file
                    try:
                        found.append((path.stat().st_mtime, path))
                    except OSError:
                        continue  # a broken link or a file removed meanwhile
            found.sort(key=lambda item: item[0], reverse=True)
            for mtime, path in found[:NOTES_PER_FOLDER]:
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
                lines.append(f"{path.as_posix()} ({when})")
        return lines
    except (OSError, ValueError, OverflowError):
        return []


def plan_excerpt(cwd: str, deadline: float) -> str:
    """plan_state.py --excerpt for cwd, or "" when there is no plan, no script or no time."""
    left = min(EXCERPT_SECONDS, deadline - time.monotonic())
    if left < MIN_CALL_SECONDS or not PLAN_STATE.is_file():
        return ""
    try:
        result = subprocess.run([sys.executable, "-B", str(PLAN_STATE), "--excerpt", "--cwd", cwd,
                                 "--max-chars", str(EXCERPT_CHARACTERS)],
                                capture_output=True, text=True, timeout=left, check=False)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


JSON_SHAPES = {
    "gemini": lambda text: {"hookSpecificOutput": {"additionalContext": text}},
    "copilot": lambda text: {"additionalContext": text},
    "cursor": lambda text: {"additional_context": text},
}


def tool_name() -> str:
    args = sys.argv[1:]
    return args[args.index("--tool") + 1] if "--tool" in args[:-1] else "claude"


def main() -> int:
    tool = tool_name()
    try:
        text = refresh(tool)
    except Exception:  # a broken refresh never fails the session or breaks a JSON reader
        text = ""
    if tool in JSON_SHAPES:
        print(json.dumps(JSON_SHAPES[tool](text) if text else {}))
    elif text:
        print(text)
    return 0


def refresh(tool: str) -> str:
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        payload = json.load(sys.stdin)
    except (ValueError, RecursionError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    roots = payload.get("workspace_roots")
    root = roots[0] if isinstance(roots, list) and roots and isinstance(roots[0], str) else "."
    cwd = text_field(payload, "cwd", root)
    source = text_field(payload, "source", "startup" if tool == "cursor" else "resume or compaction")
    excerpt = plan_excerpt(cwd, deadline)
    if source in ("startup", "clear", "new"):
        return excerpt
    # Before git, so a slow git cannot leave the notes out.
    notes = [] if excerpt else task_notes(cwd, min(deadline, time.monotonic() + NOTES_SECONDS))

    lines = [
        f"Session restarted from {source}. Everything you remember about the code is a "
        "summary and may be stale: functions may have been renamed or removed. Before "
        "editing or calling code, re-read the files involved and confirm each symbol "
        "with a search; state in one line what you will change before each edit.",
    ]
    if source == "compact":
        lines.append(SKILL_AGAIN)
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
        listed, problem = git("worktree", "list", "--porcelain", cwd=cwd, deadline=deadline)
        if problem == TIMED_OUT:
            lines.append(f"Other worktrees not shown: git worktree list {problem}.")
        elif listed:
            others = other_worktrees(listed, cwd)
            shown = others[:MAX_WORKTREES]
            more = len(others) - len(shown)
            if shown:
                lines.append("Other worktrees of this repository:\n" + "\n".join(shown)
                             + (f"\n... and {more} more" if more > 0 else ""))
    if excerpt:
        lines.append(excerpt)
        lines.append(REREAD)
    elif notes:
        lines.append("Task notes (git-ignored), most recent first:\n" + "\n".join(notes))
        lines.append(REREAD)
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
